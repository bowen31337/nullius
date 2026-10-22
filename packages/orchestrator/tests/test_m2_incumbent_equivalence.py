"""Feature 2, the M2 fixed incumbent -- ``additions_spec_dreaming_m3.xml``,
"Dreaming Loop M3 Gate".

*System ships the M2 fixed commit rule written in the question.* policy
contract as deploy/dreaming/incumbent.m2.py, so that the first dreaming
incumbent is the baseline itself and replaying it reproduces close-out's
m2-fixed pick on every world.*

This suite drives :func:`orchestrator.closeout.close_out` and
:func:`orchestrator._financial_eval.score_on_financial_world` over the
*same* fixture campaign and asserts they commit the identical node (or the
identical miss), with the identical out-of-sample score -- the equivalence
the feature sentence names. Campaigns are built the way
``test_closeout_commit_oos.py`` builds them (a sealed sidecar over a
planted null/real split, a node planted per the live evaluator's own row
shape), narrowed to the two tables that path and this suite's own
(``campaign``, ``node``) both need -- the lighter migration set
``test_dream_financial_worlds.py`` already proves is enough to drive
:func:`score_on_financial_world` directly.

``evaluate_on_dates`` is stubbed identically on both
:mod:`orchestrator.closeout` and :mod:`orchestrator._financial_eval` --
the same choice ``test_dream_financial_worlds.py`` makes for the same
reason: it is the expensive, sandboxed act a real sealed snapshot and a
real sandbox would otherwise require, and a real evaluator's own
correctness is ``test_closeout_commit_oos.py``'s concern, not this
equivalence suite's. The stub is a pure function of ``node_id`` alone, so
two calls naming the *same* committed node answer the identical score
without coincidence, while two calls that (wrongly) named different nodes
would almost certainly disagree -- the comparison has teeth.

The four fixtures below plant every node with ``ic_mean == ic_tstat``: the
dreaming side's own reading (``orchestrator._live_tree``'s ``ic_insample``,
which falls back to ``ic_tstat`` because this fixture's ``node`` table never
carries ``ir_tstat``) must equal close-out's own fallback selection value
(``ic_tstat``) for the two paths to ever agree, and setting ``ic_mean`` equal
to ``ic_tstat`` is one way to make that true. A fifth fixture,
:func:`test_fallback_reads_ic_tstat_not_ic_mean_when_the_two_readings_disagree`,
plants the two readings *distinctly* instead -- the shape close-out's own 84
real campaigns actually take, and the one this suite's equal-by-construction
convention could never catch a wrong fallback against: it pins the regression
this module was fixed for, deploy/dreaming/incumbent.m2.py failing to
reproduce close-out's pick because ``orchestrator._live_tree`` folded a
node's reading into ``ic_mean`` rather than close-out's own ``ic_tstat``
fallback.

Four fixtures, one per claim the feature's test list makes: a clear winner
(several nodes clear the bar, one strictly highest), a tie (two nodes share
the top value, broken by node id ascending), a below-bar campaign (no node
clears the bar -- a miss on both paths), and a single eligible node (only
one node clears the bar at all). A sixth test asserts
``policy_runtime.screen_policy`` adopts the module unchanged.

No test opens a network connection or reads a real credential, and no state
is kept at module scope across tests, so the suite passes under
pytest-xdist.
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
from types import ModuleType, SimpleNamespace
from typing import Any
from urllib.parse import unquote, urlparse

import discovery
import ledger
import nulloracle
import policy_runtime
import pytest
import scoring
from artifacts import ArtifactStore
from orchestrator import _financial_eval, closeout
from orchestrator._financial_eval import FinancialEvalContext, score_on_financial_world
from orchestrator.closeout import DISCOVERY_TSTAT, close_out
from replay import NON_COMMITTING_SCORE

# conftest-less suite: this file is under packages/orchestrator/tests, so the
# repository root is three parents up, the resolution every sibling closeout
# and dream suite uses.
REPO_ROOT = Path(__file__).resolve().parents[3]
VERSIONS_DIR = REPO_ROOT / "migrations" / "versions"
INCUMBENT_M2_PATH = REPO_ROOT / "deploy" / "dreaming" / "incumbent.m2.py"

CAMPAIGN_MIGRATION = "0111_campaign_table"
NODE_TABLE_MIGRATIONS = ("0118_node_table", "0114_node_metrics")

EVALUATOR_HASH = hashlib.sha256(b"m2-incumbent-equivalence-test-evaluator").hexdigest()
SNAPSHOT_HASH = hashlib.sha256(b"m2-incumbent-equivalence-test-snapshot").hexdigest()
COST_MODEL_HASH = hashlib.sha256(b"m2-incumbent-equivalence-test-cost-model").hexdigest()

# This suite's own coupling to the policy's hardcoded threshold: incumbent.m2.py
# cannot import orchestrator.closeout (the sandboxed policy runtime reaches only
# the deterministic allowlist), so its own schedule restates DISCOVERY_TSTAT's
# value as a literal. This assertion makes that coupling visible rather than
# silent -- a change to one without the other is exactly what this suite exists
# to catch, via the commit equivalence below, but this line names the premise.
assert DISCOVERY_TSTAT == 2.0


def _m2_source() -> str:
    return INCUMBENT_M2_PATH.read_text()


def _load_migration(revision: str) -> ModuleType:
    path = VERSIONS_DIR / f"{revision}.py"
    if not path.is_file():
        raise AssertionError(f"{revision} is not at {path}")
    spec = importlib.util.spec_from_file_location(
        f"_m2_incumbent_equivalence_test_{revision}", path
    )
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def database_url(tmp_path: Path) -> str:
    """A ``sqlite:///`` URL for a throwaway database, carrying only the
    ``campaign`` and ``node`` tables -- the two this suite's two call paths
    (:func:`close_out` and :func:`score_on_financial_world`) both read, the
    same lighter set ``test_dream_financial_worlds.py`` already proves is
    enough to drive a financial-world replay directly."""
    url = f"sqlite:///{tmp_path / 'm2-incumbent-equivalence.db'}"
    _load_migration(CAMPAIGN_MIGRATION).apply(url)
    for revision in NODE_TABLE_MIGRATIONS:
        _load_migration(revision).apply(url)
    return url


def _path_of(database_url: str) -> Path:
    parsed = urlparse(database_url)
    return Path(unquote(parsed.path).removeprefix("/"))


def _plant_node(database_url: str, campaign_id: str, *, node_id: str, value: float) -> str:
    """Plant one evaluated root node with ``ic_mean == ic_tstat == value``.

    Every node here is planted as a root (no ``parent_id``) -- the same
    shape ``test_closeout_commit_oos.py`` and ``test_dream_financial_
    worlds.py`` both plant -- so each campaign's tree needs no parent chain
    for its winner to be reached. ``ic_mean`` and ``ic_tstat`` are set equal
    so that :mod:`orchestrator._live_tree`'s ``ic_insample`` (the fallback
    to ``ic_mean``, since this table never carries ``ir_tstat``) reads the
    identical number close-out's own fallback selection value (``ic_tstat``)
    reads -- the equality this suite's equivalence claim depends on.
    """
    with closing(sqlite3.connect(_path_of(database_url))) as connection, connection:
        connection.execute(
            "INSERT INTO node (id, parent_id, campaign_id, theme_root, depth, "
            "ic_mean, ic_tstat) VALUES (?, NULL, ?, ?, 0, ?, ?)",
            (node_id, campaign_id, "macro", value, value),
        )
    return node_id


def _plant_node_with_metrics(
    database_url: str, campaign_id: str, *, node_id: str, ic_mean: float, ic_tstat: float
) -> str:
    """Plant one evaluated root node whose ``ic_mean`` and ``ic_tstat`` differ.

    Every fixture above plants the two equal, by construction, so that the
    pre-fix ``orchestrator._live_tree`` -- whose ``ic_insample`` fell back to
    ``ic_mean`` rather than close-out's own fallback, ``ic_tstat`` -- could
    not be told apart from a correct reading by this suite. This helper is
    for the one test that must tell them apart: it plants the two readings
    distinctly, so a path that reads the wrong one picks a different node
    (or no node) than close-out's own ``_commit_top_node`` does.
    """
    with closing(sqlite3.connect(_path_of(database_url))) as connection, connection:
        connection.execute(
            "INSERT INTO node (id, parent_id, campaign_id, theme_root, depth, "
            "ic_mean, ic_tstat) VALUES (?, NULL, ?, ?, 0, ?, ?)",
            (node_id, campaign_id, "macro", ic_mean, ic_tstat),
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


def _build_campaign(
    database_url: str,
    tmp_path: Path,
    *,
    null_values: tuple[float, ...],
    real_values: tuple[float, ...],
) -> tuple[str, dict[str, str], dict[str, float]]:
    """A Type-R campaign with ``null_values`` planted as null roots and
    ``real_values`` as real ones -- the same interleaved recipe
    ``test_closeout_commit_oos.py``'s own fixtures use. Answers the campaign
    id, its resolved environment, and every planted node's own value, keyed
    by node id -- the ground truth :func:`_expected_commit` below reads to
    compute the pick both call paths are asked to reproduce."""
    campaign_id = str(uuid.uuid4())
    discovery.create_campaign(
        discovery.TYPE_R_CAMPAIGN_TYPE, 4, campaign_id=campaign_id, database_url=database_url,
    )
    null_ids = [
        _plant_node(database_url, campaign_id, node_id=str(uuid.uuid4()), value=v)
        for v in null_values
    ]
    real_ids = [
        _plant_node(database_url, campaign_id, node_id=str(uuid.uuid4()), value=v)
        for v in real_values
    ]
    all_ids = null_ids + real_ids
    for index, node_id in enumerate(all_ids):
        _charge_ledger(database_url, node_id, campaign_id, epoch_id=f"epoch-{index}")
    assignments = [_assignment(campaign_id, n, is_null=True) for n in null_ids]
    assignments += [_assignment(campaign_id, n, is_null=False) for n in real_ids]
    env = {"DATABASE_URL": database_url, **_seal_sidecar(tmp_path, assignments)}
    node_values = dict(zip(null_ids, null_values)) | dict(zip(real_ids, real_values))
    return campaign_id, env, node_values


def _expected_commit(node_values: dict[str, float]) -> str | None:
    """The pick ``orchestrator.closeout._commit_top_node`` makes over
    ``node_values`` -- called directly, never reimplemented, so the ground
    truth both call paths are checked against is literally the function the
    feature names rather than this suite's own restatement of its rule.
    ``ic_mean`` and ``ic_tstat`` are both set to each node's planted value
    (this suite's own equal-by-construction convention) and ``ir_tstat`` is
    left ``None``, the same fallback shape every fixture in this suite
    plants on the ``node`` table."""
    evaluated = [
        closeout._EvaluatedNode(
            node_id=node_id,
            ic_mean=value,
            ic_tstat=value,
            perturb_stability=None,
            ir_tstat=None,
        )
        for node_id, value in node_values.items()
    ]
    termination = closeout._commit_top_node(evaluated)
    return termination.pick.node_id if termination.committed else None


def _write_code_artifact(artifact_dir: Path, campaign_id: str, node_id: str) -> None:
    store = ArtifactStore(artifact_dir)
    store.write(campaign_id, node_id, "code.py", "# a stored node's signal\n")
    store.commit(campaign_id, node_id)


def _fake_evaluation_context(*, database_url: str, artifact_dir: Path) -> Any:
    """A duck-typed stand-in for :class:`orchestrator._context.
    EvaluationContext` -- every field either call path reads by attribute
    before reaching the stubbed ``evaluate_on_dates``
    (:func:`orchestrator._live_tree.live_question`'s ``database_url``/
    ``evaluation_dates``, :func:`orchestrator._targets.
    snapshot_forward_returns`'s ``closes``/``horizon``, both paths' own
    ``artifact_dir``/``oos_dates``) and nothing the stub itself would need,
    the same recipe ``test_dream_financial_worlds.py`` uses for the same
    reason."""
    return SimpleNamespace(
        database_url=database_url,
        artifact_dir=artifact_dir,
        evaluation_dates=(dt.date(2026, 1, 1),),
        oos_dates=(dt.date(2026, 6, 1),),
        closes={},
        horizon=1,
        # additions_spec_dedup_committed_constructs.xml: close_out reads the
        # switch off the context before the commit, so a stand-in that
        # duck-types the record must carry it.  False is today's rule, the
        # one both call paths in this suite are checking equivalence for.
        dedup_committed_constructs=False,
    )


def _stub_evaluate_on_dates(
    node_id: str, _code: str, *, context: Any, oracle: Any, dates: Any
) -> tuple[Any, float]:
    """A deterministic stand-in for the real, sandboxed evaluator.

    Monkeypatched identically onto both ``orchestrator.closeout`` and
    ``orchestrator._financial_eval``'s own ``evaluate_on_dates`` name, so
    close-out's OOS read and the dreaming replay's OOS read each call this
    same pure function of ``node_id`` -- the identical score this suite
    asserts for the identical committed node is therefore not a coincidence
    of two separately sealed worlds, and two calls naming *different* nodes
    would (with overwhelming probability) disagree. A real evaluator's own
    correctness -- a sealed snapshot, a real sandbox, a real signal -- is
    ``test_closeout_commit_oos.py``'s concern, not this equivalence suite's.
    """
    digest = hashlib.sha256(node_id.encode("utf-8")).hexdigest()
    ir = (int(digest[:8], 16) % 2000 - 1000) / 1000.0
    metrics = SimpleNamespace(ic_tstat=2.5)
    return metrics, ir


def _run_scenario(
    database_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    null_values: tuple[float, ...],
    real_values: tuple[float, ...],
) -> tuple[Any, Any, str | None]:
    """Build one fixture campaign and replay both call paths over it.

    Answers ``(close_out_result, financial_terminal_pick, expected_winner)``
    so each test below can assert the equivalence the feature names: both
    paths commit ``expected_winner`` (or both miss), and their scores agree.
    """
    campaign_id, env, node_values = _build_campaign(
        database_url, tmp_path, null_values=null_values, real_values=real_values
    )
    expected = _expected_commit(node_values)
    artifact_dir = tmp_path / "artifacts"
    if expected is not None:
        _write_code_artifact(artifact_dir, campaign_id, expected)

    monkeypatch.setattr(closeout, "evaluate_on_dates", _stub_evaluate_on_dates)
    monkeypatch.setattr(_financial_eval, "evaluate_on_dates", _stub_evaluate_on_dates)

    scorer, sidecar = _resolved_scorer_and_sidecar(env)
    context = _fake_evaluation_context(database_url=database_url, artifact_dir=artifact_dir)

    result = close_out(
        campaign_id, database_url=database_url, scorer=scorer, sidecar=sidecar, context=context,
    )

    financial_context = FinancialEvalContext(evaluation=context)
    pick = score_on_financial_world(_m2_source(), campaign_id, context=financial_context)

    return result, pick, expected


# -- The four fixtures -------------------------------------------------------


def test_clear_winner_commits_the_same_node_with_the_same_score(
    database_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result, pick, expected = _run_scenario(
        database_url,
        tmp_path,
        monkeypatch,
        null_values=(0.4, 1.1, 1.8),
        real_values=(2.1, 2.6, 3.9),
    )

    assert expected is not None
    assert result.committed_pick == expected
    assert pick.pick is not None
    assert pick.pick.node_id == expected
    assert result.oos_ir == pytest.approx(pick.score, abs=1e-12)


def test_tie_breaks_by_node_id_ascending_on_both_paths(
    database_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result, pick, expected = _run_scenario(
        database_url,
        tmp_path,
        monkeypatch,
        null_values=(0.4, 1.1, 1.8),
        real_values=(2.1, 3.5, 3.5),
    )

    assert expected is not None
    assert result.committed_pick == expected
    assert pick.pick is not None
    assert pick.pick.node_id == expected
    assert result.oos_ir == pytest.approx(pick.score, abs=1e-12)


def test_below_bar_campaign_misses_on_both_paths(
    database_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Captures the financial side's own episode-commit record -- the same
    # recipe test_dream_financial_worlds.py's
    # test_abstaining_policy_returns_a_miss_whose_record_reports_abstained
    # uses -- so this test can assert not only that the replay misses but
    # that incumbent.m2.py's select declared the miss through
    # question.abstain() rather than falling off silently.
    records: list[Any] = []
    real_episode_commit = _financial_eval.episode_commit

    def _capturing_episode_commit(question: Any) -> Any:
        record = real_episode_commit(question)
        records.append(record)
        return record

    monkeypatch.setattr(_financial_eval, "episode_commit", _capturing_episode_commit)

    result, pick, expected = _run_scenario(
        database_url,
        tmp_path,
        monkeypatch,
        null_values=(0.4, 1.1, 1.8),
        real_values=(0.9, 1.5, 1.9),
    )

    assert expected is None
    assert result.committed_pick is None
    assert result.oos_ir is None
    assert pick.pick is None
    assert pick.score == NON_COMMITTING_SCORE
    assert len(records) == 1
    assert records[0].abstained is True
    assert records[0].committed is False


def test_single_eligible_node_commits_it_on_both_paths(
    database_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result, pick, expected = _run_scenario(
        database_url,
        tmp_path,
        monkeypatch,
        null_values=(0.4, 1.1, 1.8),
        real_values=(1.0, 1.5, 2.3),
    )

    assert expected is not None
    assert result.committed_pick == expected
    assert pick.pick is not None
    assert pick.pick.node_id == expected
    assert result.oos_ir == pytest.approx(pick.score, abs=1e-12)


def test_fallback_reads_ic_tstat_not_ic_mean_when_the_two_readings_disagree(
    database_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The defect this suite exists to catch (deploy/dreaming/incumbent.m2.py
    did not reproduce close-out's pick on real campaigns): a node whose
    ``ic_mean`` would win under a fallback that (wrongly) read ``ic_mean``,
    but whose ``ic_tstat`` -- close-out's own fallback for a node with no
    ``ir_tstat`` -- leaves it below the discovery bar, paired with a second
    node whose low ``ic_mean`` hides a bar-clearing ``ic_tstat``. Both call
    paths must commit the ``ic_tstat``-eligible node, not the higher-``ic_mean``
    one a reader comparing only ``ic_mean`` would expect.
    """
    campaign_id = str(uuid.uuid4())
    discovery.create_campaign(
        discovery.TYPE_R_CAMPAIGN_TYPE, 4, campaign_id=campaign_id, database_url=database_url,
    )
    null_ids = [
        _plant_node(database_url, campaign_id, node_id=str(uuid.uuid4()), value=v)
        for v in (0.4, 1.1, 1.8)
    ]
    high_mean_low_tstat = _plant_node_with_metrics(
        database_url, campaign_id, node_id=str(uuid.uuid4()), ic_mean=5.0, ic_tstat=1.0
    )
    low_mean_high_tstat = _plant_node_with_metrics(
        database_url, campaign_id, node_id=str(uuid.uuid4()), ic_mean=0.1, ic_tstat=2.5
    )
    real_ids = [high_mean_low_tstat, low_mean_high_tstat]
    all_ids = null_ids + real_ids
    for index, node_id in enumerate(all_ids):
        _charge_ledger(database_url, node_id, campaign_id, epoch_id=f"epoch-{index}")
    assignments = [_assignment(campaign_id, n, is_null=True) for n in null_ids]
    assignments += [_assignment(campaign_id, n, is_null=False) for n in real_ids]
    env = {"DATABASE_URL": database_url, **_seal_sidecar(tmp_path, assignments)}

    evaluated = [
        closeout._EvaluatedNode(
            node_id=high_mean_low_tstat, ic_mean=5.0, ic_tstat=1.0, perturb_stability=None, ir_tstat=None,
        ),
        closeout._EvaluatedNode(
            node_id=low_mean_high_tstat, ic_mean=0.1, ic_tstat=2.5, perturb_stability=None, ir_tstat=None,
        ),
    ]
    termination = closeout._commit_top_node(evaluated)
    expected = termination.pick.node_id if termination.committed else None
    # The premise this test is built on: close-out's own rule picks the
    # bar-clearing ic_tstat, not the bar-clearing ic_mean.
    assert expected == low_mean_high_tstat

    # Both real nodes carry an artifact -- a real campaign evaluates and
    # stores every node's code, not only the one later committed to -- so a
    # policy that (wrongly) reached for the other real node would still find
    # code to score, and this test's own assertions (not a missing artifact)
    # are what tell the two readings apart.
    artifact_dir = tmp_path / "artifacts"
    _write_code_artifact(artifact_dir, campaign_id, high_mean_low_tstat)
    _write_code_artifact(artifact_dir, campaign_id, low_mean_high_tstat)

    monkeypatch.setattr(closeout, "evaluate_on_dates", _stub_evaluate_on_dates)
    monkeypatch.setattr(_financial_eval, "evaluate_on_dates", _stub_evaluate_on_dates)

    scorer, sidecar = _resolved_scorer_and_sidecar(env)
    context = _fake_evaluation_context(database_url=database_url, artifact_dir=artifact_dir)

    result = close_out(
        campaign_id, database_url=database_url, scorer=scorer, sidecar=sidecar, context=context,
    )
    financial_context = FinancialEvalContext(evaluation=context)
    pick = score_on_financial_world(_m2_source(), campaign_id, context=financial_context)

    assert result.committed_pick == low_mean_high_tstat
    assert pick.pick is not None
    assert pick.pick.node_id == low_mean_high_tstat
    assert result.oos_ir == pytest.approx(pick.score, abs=1e-12)


# -- Admission ----------------------------------------------------------------


def test_screen_policy_adopts_the_module_unchanged() -> None:
    decision = policy_runtime.screen_policy(_m2_source())

    assert decision.adopted, decision.detail
    assert decision.reason is policy_runtime.AdmissionReason.CLEAN
