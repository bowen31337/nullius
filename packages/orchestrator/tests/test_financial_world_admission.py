"""Feature 5, the campaign grid -- ``additions_spec_engine_edge_recovery.xml``,
"System scores a stored node out of sample at its own campaign's horizon and
admits as a financial world only a campaign whose in-sample grid ended before
the first out-of-sample date".

Two laws, one suite:

* **Native horizon** -- a pick is judged on the horizon it was selected for.
  :func:`orchestrator._financial_eval._oos_ir` reads the ``campaign`` row's
  own ``horizon`` and, when it records one, hands ``evaluate_on_dates`` an
  evaluation re-horizoned through ``dataclasses.replace``; the cache key
  gains the horizon.  A ``NULL`` horizon (or a database whose chain has not
  reached ``0120``) scores at the context's horizon, exactly as before the
  feature.
* **Clean-grid admission** -- a world is never data its campaign already
  saw.  :func:`orchestrator._financial_eval.admit_financial_worlds`, the one
  shared helper ``dream``'s cycle and ``m3_verdict``'s pool check both call,
  refuses a campaign whose ``grid_last_date`` is on or after the context's
  first out-of-sample date (the leak the M3 RESULT's erratum records: 17 of
  103 admitted worlds were not out of sample for the picks scored on them)
  and one that records no ``grid_last_date`` at all; the dream summary
  displays the counts -- admitted, excluded for overlap, excluded as unknown
  -- and every excluded campaign is reported with an error message naming
  its ``grid_last_date``.

The admission tests drive the helper, the verdict's pool check and one whole
:func:`orchestrator.dream.run_cycle` over throwaway, migrated SQLite
databases; the horizon tests drive
:func:`orchestrator._financial_eval.score_on_financial_world` directly with
``evaluate_on_dates`` monkeypatched on :mod:`orchestrator._financial_eval`
(it is the expensive, sandboxed act the per-run cache exists around), and
:func:`orchestrator._financial_eval._dream_oracle` directly over real
fixture closes (no stub at all) to prove the oracle the re-horizoned
evaluation is handed serves the requested horizon out of the snapshot.  No
subprocess, no network, no credential, and no state at module scope, so the
suite passes under pytest-xdist.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import sqlite3
import uuid
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from urllib.parse import unquote, urlparse

import bootstrap
import discovery
import pytest
import replay as replay_module
from artifacts import ArtifactStore
from orchestrator import _financial_eval, m3_verdict
from orchestrator import dream as dream_module
from orchestrator._context import EVALUATION_CONFIG_ENV
from orchestrator._financial_eval import (
    FINANCIAL_ADMISSION_CODE,
    FinancialEvalContext,
    admit_financial_worlds,
    score_on_financial_world,
)

# conftest-less suite: this file is under packages/orchestrator/tests, so the
# repository root is three parents up, the resolution every sibling dream and
# closeout suite uses.
REPO_ROOT = Path(__file__).resolve().parents[3]
VERSIONS_DIR = REPO_ROOT / "migrations" / "versions"

CAMPAIGN_MIGRATION = "0111_campaign_table"
GRID_MIGRATION = "0120_campaign_evaluation_grid"
NODE_TABLE_MIGRATIONS = ("0118_node_table", "0114_node_metrics")

#: The first out-of-sample date every context in this suite carries -- the
#: admission anchor, and the date a clean fixture grid ends strictly before.
OOS_FIRST = dt.date(2026, 6, 1)
CLEAN_GRID_FIRST = "2026-05-01"
CLEAN_GRID_LAST = "2026-05-31"

# The cycle test reuses test_dream_financial_worlds.py's own pool figures --
# 40 worlds (the 20-50 rung, M = 10) and the seed already confirmed tie-free
# for this incumbent source at this round cap -- because its subject is the
# admission beside an otherwise ordinary cycle, not the ladder.
POOL_WORLD_COUNT = 40
POOL_SEED = 20261006
ROUND_CAP = 5

EVALUATION_CONFIG_BYTES = b'{"pinned": "fixture-admission-config"}\n'

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


@dataclass(frozen=True)
class _StubContext:
    """A stand-in for :class:`orchestrator._context.EvaluationContext`.

    Every field the scorer path reads by attribute, and a **frozen
    dataclass** rather than a ``SimpleNamespace`` because feature 5's
    native-horizon law re-horizons the evaluation through
    ``dataclasses.replace(context.evaluation, horizon=...)`` -- the one
    operation this suite's paths perform on the context beyond attribute
    reads.
    """

    database_url: str
    artifact_dir: Path
    evaluation_dates: tuple[dt.date, ...]
    oos_dates: tuple[dt.date, ...]
    closes: dict[Any, Any]
    horizon: int
    cost_model_hash: str = "a"


def _load_migration(revision: str) -> ModuleType:
    path = VERSIONS_DIR / f"{revision}.py"
    if not path.is_file():
        raise AssertionError(f"{revision} is not at {path}")
    spec = importlib.util.spec_from_file_location(
        f"_orchestrator_financial_admission_test_{revision}", path
    )
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sqlite_path(database_url: str) -> Path:
    parsed = urlparse(database_url)
    return Path(unquote(parsed.path).removeprefix("/"))


def _campaign_database(tmp_path: Path, name: str, *, grid: bool = True) -> str:
    """A database carrying the campaign, node and (unless ``grid=False``) grid
    tables -- the admission's and the scorer's whole schema, nothing else."""
    database_url = f"sqlite:///{tmp_path / name}"
    _load_migration(CAMPAIGN_MIGRATION).apply(database_url)
    if grid:
        _load_migration(GRID_MIGRATION).apply(database_url)
    for revision in NODE_TABLE_MIGRATIONS:
        _load_migration(revision).apply(database_url)
    return database_url


def _pool_database(tmp_path: Path) -> str:
    """The campaign schema above, plus the bootstrap pool and ``0109``'s
    replay tables a whole dreaming cycle touches."""
    database_url = _campaign_database(tmp_path, "admission-cycle.db")
    bootstrap.BootstrapPool(database_url).persist_worlds(
        POOL_WORLD_COUNT, pool_seed=POOL_SEED
    )
    _load_migration("0109_replay_score_and_policy_revision").apply(database_url)
    return database_url


def _plant_node(
    database_url: str, campaign_id: str, *, node_id: str, ic_mean: float = 0.4
) -> None:
    """Plant one evaluated root node -- the state a finished campaign's own
    live evaluator would have written (the sibling dream suite's recipe)."""
    with closing(sqlite3.connect(_sqlite_path(database_url))) as connection, connection:
        connection.execute(
            "INSERT INTO node (id, parent_id, campaign_id, theme_root, depth, "
            "ic_mean, ic_tstat) VALUES (?, NULL, ?, ?, 0, ?, 1.0)",
            (node_id, campaign_id, "macro", ic_mean),
        )


def _build_campaign(
    database_url: str,
    *,
    horizon: int | None = None,
    grid_first_date: str | None = None,
    grid_last_date: str | None = None,
    oos_first_date: str | None = None,
    void: bool = False,
) -> tuple[str, str]:
    """A minimal completed campaign: one root node, finished, its grid exactly
    what the caller asked the admission to judge.  ``(campaign_id, node_id)``.

    The default call records no grid at all -- the ``NULL``-column shape
    campaigns recorded before ``0120`` still carry -- and the suite's own
    helpers layer the named values on top, so what a clean grid, a dirty grid
    and an absent grid each mean is always one keyword away from the reader.
    """
    campaign_id = str(uuid.uuid4())
    discovery.create_campaign(
        discovery.TYPE_R_CAMPAIGN_TYPE,
        4,
        campaign_id=campaign_id,
        database_url=database_url,
        horizon=horizon,
        grid_first_date=grid_first_date,
        grid_last_date=grid_last_date,
        oos_first_date=oos_first_date,
    )
    node_id = str(uuid.uuid4())
    _plant_node(database_url, campaign_id, node_id=node_id)
    if void:
        with closing(sqlite3.connect(_sqlite_path(database_url))) as connection, connection:
            connection.execute(
                "UPDATE campaign SET calibration_status = 'VOID' WHERE id = ?",
                (campaign_id,),
            )
    discovery.finish_campaign(campaign_id, database_url=database_url)
    return campaign_id, node_id


def _clean_campaign(database_url: str, *, horizon: int = 1) -> tuple[str, str]:
    """A campaign whose in-sample grid ends strictly before :data:`OOS_FIRST`
    -- admitted under the clean-grid rule whatever else it records."""
    return _build_campaign(
        database_url,
        horizon=horizon,
        grid_first_date=CLEAN_GRID_FIRST,
        grid_last_date=CLEAN_GRID_LAST,
        oos_first_date=OOS_FIRST.isoformat(),
    )


def _write_code_artifact(artifact_dir: Path, campaign_id: str, node_id: str) -> None:
    store = ArtifactStore(artifact_dir)
    store.write(campaign_id, node_id, "code.py", "# a stored node's signal\n")
    store.commit(campaign_id, node_id)


def _fake_context(
    database_url: str,
    artifact_dir: Path,
    *,
    horizon: int = 1,
    closes: dict[Any, Any] | None = None,
) -> FinancialEvalContext:
    return FinancialEvalContext(
        evaluation=_StubContext(
            database_url=database_url,
            artifact_dir=artifact_dir,
            evaluation_dates=(dt.date(2026, 1, 1),),
            oos_dates=(OOS_FIRST,),
            closes={} if closes is None else closes,
            horizon=horizon,
        )
    )


def _counting_stub(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, tuple, int]]:
    """Monkeypatch ``evaluate_on_dates`` with a deterministic, call-counted
    stub recording ``(node_id, dates, horizon)`` -- the horizon the evaluation
    was actually handed, which is the whole of what the native-horizon law
    claims."""
    calls: list[tuple[str, tuple, int]] = []

    def _stub(
        node_id: str, _code: str, *, context: Any, oracle: Any, dates: Any
    ) -> tuple[Any, float]:
        calls.append((node_id, tuple(dates), context.horizon))
        return SimpleNamespace(), 0.1 + 0.01 * len(calls)

    monkeypatch.setattr(_financial_eval, "evaluate_on_dates", _stub)
    return calls


# -- The native horizon ---------------------------------------------------------


def test_a_campaigns_own_horizon_is_the_horizon_the_pick_is_judged_at(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The law's positive half: a campaign that recorded ``horizon = 5`` is
    scored at 5, whatever horizon the dreaming context itself carries -- a
    pick is judged on the horizon it was selected for.

    The horizon is observed at both seams the spec names: the evaluation the
    scorer hands ``evaluate_on_dates`` (its own ``horizon`` field, through
    the stub) and **the oracle request's horizon** -- the stub asks the very
    oracle the scorer built, with a request labelled by that horizon over
    real fixture closes, and the answer that comes back is the 5-trading-day
    close-to-close return, the horizon the pick was selected for served out
    of the snapshot's real forward returns.
    """
    database_url = _campaign_database(tmp_path, "horizon-native.db")
    campaign_id, node_id = _clean_campaign(database_url, horizon=5)
    artifact_dir = tmp_path / "artifacts"
    _write_code_artifact(artifact_dir, campaign_id, node_id)

    # Eight trading days from the OOS grid's first date, close[i] = 100 + i:
    # the grid date's own 5-day forward return is 105/100 - 1.
    days = [OOS_FIRST + dt.timedelta(days=i) for i in range(8)]
    closes = {day: float(100 + index) for index, day in enumerate(days)}
    context = _fake_context(
        database_url, artifact_dir, horizon=1, closes={"AAA": closes}
    )

    observed: list[tuple[tuple, int, dict]] = []

    def _stub(
        _node_id: str,
        _code: str,
        *,
        context: Any,
        oracle: Any,
        dates: Any,
    ) -> tuple[Any, float]:
        # Ask the oracle the scorer handed us, once, labelled with the
        # horizon the evaluation carries -- the request's own horizon, the
        # seam the spec's parenthetical names.
        answer = oracle(
            SimpleNamespace(horizon=context.horizon, symbols=("AAA",), date_range=None)
        )
        observed.append((tuple(dates), context.horizon, answer.target_series))
        return SimpleNamespace(), 0.1

    monkeypatch.setattr(_financial_eval, "evaluate_on_dates", _stub)

    result = score_on_financial_world(INCUMBENT_SOURCE, campaign_id, context=context)

    assert result.pick is not None and result.pick.node_id == node_id
    assert observed == [((OOS_FIRST,), 5, {OOS_FIRST: {"AAA": pytest.approx(0.05)}})]
    # The horizon is part of the measurement, so it is part of the cache key.
    assert (node_id, (OOS_FIRST,), 5) in context._cache
    # The re-horizoning replaced, never mutated: the context the caller built
    # still carries its own horizon for every other campaign it scores.
    assert context.evaluation.horizon == 1


def test_a_null_horizon_scores_at_the_contexts_own_horizon(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A campaign that records no horizon (the pre-``0120`` shape) is scored
    at the context's horizon, exactly as it always was -- the feature adds a
    law for campaigns that carry the column, not a new refusal for ones that
    do not."""
    database_url = _campaign_database(tmp_path, "horizon-null.db")
    campaign_id, node_id = _clean_campaign(database_url, horizon=1)
    with closing(sqlite3.connect(_sqlite_path(database_url))) as connection, connection:
        connection.execute(
            "UPDATE campaign SET horizon = NULL WHERE id = ?", (campaign_id,)
        )
    artifact_dir = tmp_path / "artifacts"
    _write_code_artifact(artifact_dir, campaign_id, node_id)
    calls = _counting_stub(monkeypatch)

    context = _fake_context(database_url, artifact_dir, horizon=3)

    score_on_financial_world(INCUMBENT_SOURCE, campaign_id, context=context)

    assert calls == [(node_id, (OOS_FIRST,), 3)]
    assert (node_id, (OOS_FIRST,), 3) in context._cache


def test_a_pre_grid_schema_scores_at_the_contexts_own_horizon(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A database whose chain never reached ``0120`` has no ``horizon``
    column at all; the scorer must read that as "no horizon of its own"
    rather than refusing -- the default path's numbers are unchanged on
    every schema the store can serve."""
    database_url = _campaign_database(tmp_path, "horizon-pre-grid.db", grid=False)
    campaign_id, node_id = _build_campaign(database_url)
    artifact_dir = tmp_path / "artifacts"
    _write_code_artifact(artifact_dir, campaign_id, node_id)
    calls = _counting_stub(monkeypatch)

    context = _fake_context(database_url, artifact_dir, horizon=7)

    score_on_financial_world(INCUMBENT_SOURCE, campaign_id, context=context)

    assert calls == [(node_id, (OOS_FIRST,), 7)]


def test_the_dream_oracle_serves_the_requested_horizon_over_real_closes(
    tmp_path: Path,
) -> None:
    """The re-horizoned evaluation's oracle is the same real-return gate it
    always was, now serving the campaign's horizon: an ask labelled 5 trading
    days gets the 5-day close-to-close return, an ask labelled 1 the 1-day
    one -- proved here over real fixture closes with nothing stubbed, the
    seam the "the oracle already serves the requested horizon" half of the
    law rests on."""
    days = [dt.date(2026, 5, 1) + dt.timedelta(days=i) for i in range(8)]
    closes = {day: float(100 + index) for index, day in enumerate(days)}
    context = SimpleNamespace(closes={"AAA": closes}, horizon=5)

    oracle = _financial_eval._dream_oracle(context, (days[0], days[3]))

    five_day = oracle(SimpleNamespace(horizon=5, symbols=("AAA",), date_range=None))
    one_day = oracle(SimpleNamespace(horizon=1, symbols=("AAA",), date_range=None))

    # Entry index i's return is close[i + h] / close[i] - 1, omitted (never
    # zero-filled) where the series has no close that far ahead: index 3 has
    # no 5-day forward close, index 7 no 1-day one.
    assert five_day.target_series == {
        days[0]: {"AAA": pytest.approx(105.0 / 100.0 - 1.0)}
    }
    assert one_day.target_series == {
        days[0]: {"AAA": pytest.approx(101.0 / 100.0 - 1.0)},
        days[3]: {"AAA": pytest.approx(104.0 / 103.0 - 1.0)},
    }


# -- The clean-grid admission ----------------------------------------------------


def test_a_grid_ending_on_or_after_the_first_oos_date_is_excluded(
    tmp_path: Path,
) -> None:
    """The leak, refused: a campaign whose in-sample grid reached into the
    out-of-sample window is not a world, whichever side of the boundary its
    last date falls on -- **on** the first OOS date is overlap too, because a
    bar the grid's own last evaluation date already saw is a bar the pick was
    selected on."""
    database_url = _campaign_database(tmp_path, "overlap.db")
    clean_id, _ = _clean_campaign(database_url)
    touching_id, _ = _build_campaign(
        database_url,
        horizon=1,
        grid_first_date="2026-05-20",
        grid_last_date=OOS_FIRST.isoformat(),
        oos_first_date="2026-06-15",
    )
    inside_id, _ = _build_campaign(
        database_url,
        horizon=1,
        grid_first_date="2026-05-20",
        grid_last_date="2026-06-15",
        oos_first_date="2026-06-01",
    )

    admission = admit_financial_worlds(database_url, oos_first_date=OOS_FIRST)

    assert admission.campaign_ids == (clean_id,)
    assert sorted(admission.excluded_overlap) == sorted((touching_id, inside_id))
    assert admission.excluded_unknown == ()
    assert admission.counts() == {
        "admitted": 1,
        "excluded_overlap": 2,
        "excluded_unknown": 0,
    }
    messages = {
        exclusion.campaign_id: exclusion.message for exclusion in admission.exclusions
    }
    # An excluded campaign is reported with an error message of the
    # admission's own -- greppable, naming the grid_last_date that excluded
    # it and the boundary it crossed.
    assert messages[touching_id].startswith(FINANCIAL_ADMISSION_CODE)
    assert "2026-06-01" in messages[touching_id]  # its own grid_last_date
    assert messages[inside_id].startswith(FINANCIAL_ADMISSION_CODE)
    assert "2026-06-15" in messages[inside_id]


def test_a_campaign_with_no_recorded_grid_is_excluded_as_unknown(
    tmp_path: Path,
) -> None:
    """Unknown is not admitted: a campaign that records no ``grid_last_date``
    cannot prove its grid ended before the OOS window, and the admission
    refuses it as such -- reported with its own word, never silently folded
    into the overlap count."""
    database_url = _campaign_database(tmp_path, "unknown.db")
    clean_id, _ = _clean_campaign(database_url)
    # A horizon without a grid: the columns exist, the grid's end is NULL.
    no_grid_id, _ = _build_campaign(database_url, horizon=1)

    admission = admit_financial_worlds(database_url, oos_first_date=OOS_FIRST)

    assert admission.campaign_ids == (clean_id,)
    assert admission.excluded_overlap == ()
    assert admission.excluded_unknown == (no_grid_id,)
    message = admission.exclusions[0].message
    assert message.startswith(FINANCIAL_ADMISSION_CODE)
    assert no_grid_id in message
    assert "grid_last_date" in message


def test_with_no_oos_anchor_admission_is_unchanged(
    tmp_path: Path,
) -> None:
    """A context with no out-of-sample grid (and the M3 verdict, which holds
    the pinned configuration only by its digest) admits exactly what the
    standing ``VOID`` filter alone admitted: the dirty grid and the absent
    grid alike, the VOID campaign never, and no grid column is read at all."""
    database_url = _campaign_database(tmp_path, "no-anchor.db")
    clean_id, _ = _clean_campaign(database_url)
    dirty_id, _ = _build_campaign(
        database_url,
        horizon=1,
        grid_first_date="2026-05-20",
        grid_last_date="2026-06-15",
        oos_first_date="2026-06-01",
    )
    no_grid_id, _ = _build_campaign(database_url, horizon=1)
    # VOID is set before finish_campaign, the sibling dream suite's own
    # recipe: the manifest the admission reads carries the status.
    _void_id, _ = _build_campaign(
        database_url,
        horizon=1,
        grid_first_date=CLEAN_GRID_FIRST,
        grid_last_date=CLEAN_GRID_LAST,
        oos_first_date=OOS_FIRST.isoformat(),
        void=True,
    )

    admission = admit_financial_worlds(database_url, oos_first_date=None)

    assert sorted(admission.campaign_ids) == sorted((clean_id, dirty_id, no_grid_id))
    assert admission.exclusions == ()
    assert admission.counts() == {
        "admitted": 3,
        "excluded_overlap": 0,
        "excluded_unknown": 0,
    }


def test_an_empty_database_admits_nothing_and_refuses_nothing(
    tmp_path: Path,
) -> None:
    """A database with no completed campaign answers an empty admission under
    an anchor as under none -- the manifest store creates its own table on
    first read, and the campaign table is only ever read per manifest, so the
    anchor never turns an empty pool into a refusal."""
    database_url = f"sqlite:///{tmp_path / 'empty.db'}"

    for anchor in (None, OOS_FIRST):
        admission = admit_financial_worlds(database_url, oos_first_date=anchor)
        assert admission.campaign_ids == ()
        assert admission.exclusions == ()
        assert admission.summary() == {
            "admitted": 0,
            "excluded_overlap": 0,
            "excluded_unknown": 0,
            "excluded": {},
        }


def test_dream_cycle_summary_displays_the_counts_and_the_refusals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The sentence's own reporting claim, over a whole cycle: the summary
    displays the counts admitted, excluded for overlap and excluded as
    unknown, each excluded campaign is reported with an error message naming
    its ``grid_last_date``, and nothing the admission refused is ever swept
    or written a ``#financial`` row."""
    database_url = _pool_database(tmp_path)
    clean_a, node_a = _clean_campaign(database_url, horizon=1)
    clean_b, node_b = _clean_campaign(database_url, horizon=1)
    dirty_id, _ = _build_campaign(
        database_url,
        horizon=1,
        grid_first_date="2026-05-20",
        grid_last_date="2026-06-15",
        oos_first_date="2026-06-01",
    )
    no_grid_id, _ = _build_campaign(database_url, horizon=1)
    artifact_dir = tmp_path / "artifacts"
    for campaign_id, node_id in ((clean_a, node_a), (clean_b, node_b)):
        _write_code_artifact(artifact_dir, campaign_id, node_id)
    _counting_stub(monkeypatch)

    config_path = tmp_path / "evaluation-config.json"
    config_path.write_bytes(EVALUATION_CONFIG_BYTES)
    summary = dream_module.run_cycle(
        incumbent_source=INCUMBENT_SOURCE,
        database_url=database_url,
        iteration_id="cycle-5",
        beta=0.5,
        seed="cycle-5",
        round_cap=ROUND_CAP,
        replay_component=replay_module.ReplayEngine(),
        census=bootstrap.world_census(bootstrap.BootstrapPool(database_url)),
        pool=bootstrap.BootstrapPool(database_url),
        evaluation_context=_fake_context(database_url, artifact_dir).evaluation,
        env={EVALUATION_CONFIG_ENV: str(config_path)},
    )

    assert summary["n_financial"] == 2
    admission = summary["financial_admission"]
    assert admission["admitted"] == 2
    assert admission["excluded_overlap"] == 1
    assert admission["excluded_unknown"] == 1
    assert sorted(admission["excluded"]) == sorted((dirty_id, no_grid_id))
    assert admission["excluded"][dirty_id].startswith(FINANCIAL_ADMISSION_CODE)
    assert "2026-06-15" in admission["excluded"][dirty_id]
    assert "grid_last_date" in admission["excluded"][no_grid_id]

    # The financial arm is computed over the two admitted worlds alone...
    assert isinstance(summary["financial_arm"], dict)
    assert "unscoreable" not in summary["financial_arm"]
    # ...and no refused campaign is ever swept: no #financial row names one.
    with closing(sqlite3.connect(_sqlite_path(database_url))) as connection:
        worlds = {
            row[0]
            for row in connection.execute(
                "SELECT DISTINCT world_id FROM replay_score "
                "WHERE policy_version LIKE '%#financial%'"
            )
        }
    assert worlds == {clean_a, clean_b}


# -- The verdict's own pool check ------------------------------------------------


def test_the_verdicts_thin_pool_refusal_reports_the_counts_and_the_grid(
    tmp_path: Path,
) -> None:
    """``_verify_financial_pool`` under an anchor reports *why* the pool is
    thin: the three counts, and the first refused campaign's own error
    message naming its ``grid_last_date`` -- the operator learns which grid
    to repair, not only that the floor was missed."""
    database_url = _campaign_database(tmp_path, "verdict-thin.db")
    dirty_id, _ = _build_campaign(
        database_url,
        horizon=1,
        grid_first_date="2026-05-20",
        grid_last_date="2026-06-15",
        oos_first_date="2026-06-01",
    )
    no_grid_id, _ = _build_campaign(database_url, horizon=1)
    for _ in range(3):
        _clean_campaign(database_url)

    with pytest.raises(m3_verdict.M3VerdictError) as raised:
        m3_verdict._verify_financial_pool(database_url, oos_first_date=OOS_FIRST)

    message = str(raised.value)
    assert "3 financial world(s) are admitted" in message
    assert "1 excluded for grid overlap" in message
    assert "1 excluded with no recorded grid_last_date" in message
    # completed() orders by campaign id, so the first refused campaign is the
    # lexicographically smaller of the two -- derived here, never assumed.
    first_refused = min(dirty_id, no_grid_id)
    assert first_refused in message

    # With no anchor -- the verdict's own standing call, which holds no
    # evaluation context -- the same pool admits every completed, non-VOID
    # campaign exactly as it did before the feature: the dirty grid and the
    # absent grid beside the three clean ones, still below the floor this
    # pool cannot clear.
    admission = admit_financial_worlds(database_url, oos_first_date=None)
    assert len(admission.campaign_ids) == 5
    assert {dirty_id, no_grid_id} <= set(admission.campaign_ids)
    assert admission.exclusions == ()
    with pytest.raises(m3_verdict.M3VerdictError, match="5 financial world"):
        m3_verdict._verify_financial_pool(database_url)


def test_twenty_clean_campaigns_clear_the_verdicts_floor_under_the_anchor(
    tmp_path: Path,
) -> None:
    """The floor itself is reachable under the clean-grid rule: twenty
    campaigns whose grids all ended before the first OOS date are admitted,
    the whole pool the M3 gate requires, and nothing is refused."""
    database_url = _campaign_database(tmp_path, "verdict-floor.db")
    clean_ids = {_clean_campaign(database_url)[0] for _ in range(20)}
    assert len(clean_ids) == 20

    campaigns = m3_verdict._verify_financial_pool(
        database_url, oos_first_date=OOS_FIRST
    )

    assert set(campaigns) == clean_ids
