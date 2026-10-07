"""bug_spec_pipeline_cross_section.xml, bug (B) — flat dates are absent, not refusals.

``orchestrator._evaluate.evaluate_node`` already treats a rebalance date
whose point-in-time universe holds fewer than two symbols as absent
(bug_spec_pit_universe.xml's own fix) — but a date whose cross-section is
*wide enough* yet whose raw scores are all identical (a warm-up day before a
signal's own lookback fills, or a genuinely flat market day) still reached
``evaluator.normalize_scores`` unguarded, which refuses that vector as
"no preference" — and the refusal propagated out of ``evaluate_node``'s one
``try``, failing and charging the *whole* node for a single uninteresting
day.

The fix: ``orchestrator._evaluate._score_rebalance_dates`` checks for the
no-preference condition itself (:func:`orchestrator._evaluate._all_scores_identical`,
a direct restatement of ``normalize_scores``' own ``std_rank == 0`` check)
*before* calling ``normalize_scores``, and treats a match the same way as a
thin date: absent, ``scores[day] = {}``, never a fabricated zero. A signal
cannot pass by expressing a preference on a handful of cherry-picked days,
though: :data:`orchestrator._evaluate.MIN_SCORED_DATES` (default 20) is a
floor on how many dates must survive — scoped to this one new reason, not to
every thin date too (that floor is bug_spec_pit_universe.xml's own, already-
settled territory, and test_pit_universe_per_date.py pins a node scored over
as few as two non-thin dates succeeding).

One test per claim, first at the unit level directly against
``_score_rebalance_dates`` (fast, precise, no sandbox), then the same two
boundary claims again through the full ``evaluate_node`` pipeline (the
sandbox's real ``execute_signal`` replaced with a fixed
:class:`~evaluator.SignalExecution` via monkeypatch, so the rest of the
chain — ``align_targets``, ``gate_targets``, ``apply_costs``,
``compute_node_metrics`` — runs for real):

* a warm-up constant on the first five dates scores over the rest, with
  ``flat_dates`` on the answer naming the absent count;
* a constant on every date is refused;
* too few varied dates (more absent than :data:`MIN_SCORED_DATES` leaves
  room for) is refused;
* a non-finite vector is still refused for the whole node, unabsorbed —
  ``_all_scores_identical`` answers ``False`` for it (not finite), so it
  reaches ``normalize_scores`` and that refusal propagates rather than being
  swallowed as a flat date.

No test opens a network connection or writes outside a pytest temporary
directory, and none shares mutable state across tests, so the suite is safe
under pytest-xdist.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path
from types import ModuleType
from typing import Any

import polars as pl
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from cost_model import FeeSchedule, load_cost_model
from evaluator import EvaluatorNormalizeError, RawScoreVector, SignalExecution
from ledger import TrialLedger
from nulloracle.target import OK, TargetResponse
from orchestrator._context import EvaluationContext
from orchestrator._evaluate import MIN_SCORED_DATES, _score_rebalance_dates
from orchestrator._oracle import SubtreeOracle

REPO_ROOT = Path(__file__).resolve().parents[3]
VERSIONS_DIR = REPO_ROOT / "migrations" / "versions"
NODE_TABLE_MIGRATIONS = ("0118_node_table", "0114_node_metrics")

_UNIVERSE = ("AAA", "BBB")
_DAYS = tuple(dt.date(2026, 9, 1) + dt.timedelta(days=i) for i in range(30))


def _execution(day_scores: dict[dt.date, list[float]]) -> SignalExecution:
    """A hand-built execution — one vector per date, scores exactly as given."""
    vectors = {
        day: RawScoreVector(
            rebalance_date=day,
            decision_time=dt.datetime.combine(day, dt.time(tzinfo=dt.UTC)),
            universe=_UNIVERSE,
            seed=7,
            contract_version="0.1.0",
            scores=pl.Series(values, dtype=pl.Float64),
            problems=[],
        )
        for day, values in day_scores.items()
    }
    return SignalExecution(
        snapshot_name="snap_flat_date_test", code_hash="ab" * 32, seed=7, vectors=vectors
    )


def _varied(index: int) -> list[float]:
    """A two-symbol vector that is never identical (``index`` starts at 1).

    Alternates which symbol ranks first across dates (even vs. odd
    ``index``) rather than always preferring the same one — a signal whose
    per-date preference never varied would give ``compute_node_metrics`` a
    constant information coefficient and its own, unrelated zero-variance
    refusal, which these tests are not about.
    """
    sign = 1.0 if index % 2 else -1.0
    return [sign * float(index), -sign * float(index)]


# -- Unit level: _score_rebalance_dates directly -------------------------------


def test_a_warm_up_constant_on_the_first_five_dates_scores_over_the_rest() -> None:
    days = _DAYS[:25]
    day_scores: dict[dt.date, list[float]] = {}
    for day in days[:5]:
        day_scores[day] = [1.0, 1.0]
    for offset, day in enumerate(days[5:], start=1):
        day_scores[day] = _varied(offset)
    execution = _execution(day_scores)

    scores, flat_dates = _score_rebalance_dates(execution, "node-warmup")

    assert flat_dates == 5
    for day in days[:5]:
        assert scores[day] == {}
    for day in days[5:]:
        assert set(scores[day]) == set(_UNIVERSE)


def test_a_constant_score_on_every_date_is_refused() -> None:
    days = _DAYS[:10]
    execution = _execution({day: [2.0, 2.0] for day in days})

    with pytest.raises(EvaluatorNormalizeError, match="no preference"):
        _score_rebalance_dates(execution, "node-allflat")


def test_too_few_varied_dates_is_refused() -> None:
    days = _DAYS[:25]
    day_scores: dict[dt.date, list[float]] = {}
    for day in days[:21]:
        day_scores[day] = [3.0, 3.0]
    for offset, day in enumerate(days[21:], start=1):
        day_scores[day] = _varied(offset)
    execution = _execution(day_scores)

    with pytest.raises(EvaluatorNormalizeError, match="MIN_SCORED_DATES"):
        _score_rebalance_dates(execution, "node-toofew")


def test_a_non_finite_vector_is_still_refused_not_absorbed_as_flat() -> None:
    days = _DAYS[:3]
    execution = _execution(
        {
            days[0]: [1.0, 2.0],
            days[1]: [float("nan"), 1.0],
            days[2]: [3.0, 4.0],
        }
    )

    with pytest.raises(EvaluatorNormalizeError, match="non-finite"):
        _score_rebalance_dates(execution, "node-nonfinite")


def test_min_scored_dates_default_is_twenty() -> None:
    # Pinned because the bug text names this exact default; a change here is
    # a deliberate policy change, not a refactor.
    assert MIN_SCORED_DATES == 20


# -- Integration level: the same two boundary claims through evaluate_node ----


def _load_migration(revision: str) -> ModuleType:
    path = VERSIONS_DIR / f"{revision}.py"
    if not path.is_file():
        raise AssertionError(f"{revision} is not at {path}")
    spec = importlib.util.spec_from_file_location(
        f"_orchestrator_flat_date_test_{revision}", path
    )
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _path_of(database_url: str) -> Path:
    from urllib.parse import unquote, urlparse

    parsed = urlparse(database_url)
    return Path(unquote(parsed.path).removeprefix("/"))


def _migrate_tree(database_url: str) -> None:
    for revision in NODE_TABLE_MIGRATIONS:
        _load_migration(revision).apply(database_url)


def _plant_root(database_url: str, *, node_id: str, campaign_id: str) -> None:
    with closing(sqlite3.connect(_path_of(database_url))) as connection, connection:
        connection.execute(
            "INSERT INTO node (id, parent_id, campaign_id, theme_root, depth) "
            "VALUES (?, NULL, ?, ?, ?)",
            (node_id, campaign_id, "macro", 0),
        )


EPOCH_ID = "epoch-2026-10-07-flat-date"
EVALUATOR_HASH = "77" * 32
SNAPSHOT_HASH_FALLBACK = "88" * 32
COST_MODEL_HASH = "99" * 32
CAMPAIGN_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeefb"
WORLD_SEED = 13579


class RecordingEndpoint:
    """A fake dense ``TargetEndpoint`` — every date carries the request's
    whole cross-section, the simplest real-branch stand-in since this
    suite's fixed executions never list or delist a symbol.
    """

    def __init__(self) -> None:
        self.charges_budget = True

    def post(self, request: Any) -> TargetResponse:
        first, last = request.date_range
        series: dict[dt.date, dict[str, float]] = {}
        day = first
        while day <= last:
            # Varies by symbol (a real cross-sectional rank correlation) and
            # by date (a real equal-weight book variance) — never read from
            # a null bit, a fixed per-symbol constant would give
            # compute_node_metrics' own zero-variance book a ratio with
            # nothing to divide, unrelated to what this suite is testing.
            series[day] = {
                symbol: 0.001 * (index + 1) * (1.0 + 0.1 * (day - first).days)
                for index, symbol in enumerate(sorted(request.symbols))
            }
            day += dt.timedelta(days=1)
        return TargetResponse(
            status=OK,
            node_id=request.node_id,
            target_series=series,
            charges_budget=self.charges_budget,
        )


def _seal_minimal_world(workdir: Path, bar_days: tuple[dt.date, ...]) -> tuple[Any, dict]:
    """A real, tiny sealed snapshot over ``_UNIVERSE`` — enough for
    ``resolve_window``/``signal_sandbox`` to construct for real, since
    ``execute_signal`` itself is monkeypatched and never reads these bars.
    """
    from snapshot import SnapshotService

    lake_root = workdir / "lake"
    (lake_root / "snapshots").mkdir(parents=True)
    staging = lake_root / "staging"
    staging.mkdir()

    closes: dict[str, dict[dt.date, float]] = {symbol: {} for symbol in _UNIVERSE}
    for symbol_index, symbol in enumerate(_UNIVERSE):
        price = 100.0 + symbol_index * 10.0
        for day_index, day in enumerate(bar_days):
            price = price + 0.1 * ((day_index % 7) - 3)
            closes[symbol][day] = round(price, 2)
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
    sealed = service.seal(sealed_at=dt.datetime(2026, 11, 1, tzinfo=dt.UTC))
    mount = service.mount(sealed.name)
    return mount, closes


#: 25 evaluation dates plus one trailing bar day so horizon-1 alignment has
#: an exit price for the grid's last rebalance date.
_BAR_DAYS = tuple(dt.date(2026, 9, 1) + dt.timedelta(days=i) for i in range(26))
_EVAL_DATES = _BAR_DAYS[:25]


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> tuple[Any, dict]:
    workdir = tmp_path_factory.mktemp("flat-date-world")
    return _seal_minimal_world(workdir, _BAR_DAYS)


@pytest.fixture
def context(tmp_path: Path, world: tuple[Any, dict]) -> EvaluationContext:
    mount, closes = world
    config = load_cost_model()
    schedule = FeeSchedule(venue=config.venue, taker_bps=10.0, maker_bps=10.0)
    database_url = f"sqlite:///{tmp_path / 'flat-date.db'}"
    _migrate_tree(database_url)
    return EvaluationContext(
        snapshot=mount,
        closes=closes,
        cost_model=config,
        cost_schedule=schedule,
        evaluator_hash=EVALUATOR_HASH,
        snapshot_hash=SNAPSHOT_HASH_FALLBACK,
        cost_model_hash=COST_MODEL_HASH,
        epoch_id=EPOCH_ID,
        database_url=database_url,
        artifact_dir=tmp_path / "artifacts",
        seed=WORLD_SEED,
        horizon=1,
        evaluation_dates=_EVAL_DATES,
        sandbox_runtime="unisolated",
    )


def _evaluate_with_fixed_execution(
    monkeypatch: pytest.MonkeyPatch,
    context: EvaluationContext,
    execution: SignalExecution,
) -> Any:
    import orchestrator._evaluate as evaluate_module

    monkeypatch.setattr(evaluate_module, "execute_signal", lambda *a, **k: execution)

    node_id = str(uuid.uuid4())
    _plant_root(context.database_url, node_id=node_id, campaign_id=CAMPAIGN_ID)
    endpoint = RecordingEndpoint()
    oracle = SubtreeOracle(endpoint, database_url=context.database_url)
    ledger = TrialLedger(context.database_url)

    return evaluate_module.evaluate_node(
        node_id,
        CAMPAIGN_ID,
        0,
        "def signal(ctx, seed):\n    return None\n",
        context=context,
        oracle=oracle,
        ledger=ledger,
    )


def test_evaluate_node_scores_over_the_rest_after_a_warm_up_constant(
    monkeypatch: pytest.MonkeyPatch, context: EvaluationContext
) -> None:
    day_scores: dict[dt.date, list[float]] = {}
    for day in _EVAL_DATES[:5]:
        day_scores[day] = [1.0, 1.0]
    for offset, day in enumerate(_EVAL_DATES[5:], start=1):
        day_scores[day] = _varied(offset)
    execution = _execution(day_scores)

    answer = _evaluate_with_fixed_execution(monkeypatch, context, execution)

    assert answer.fail_class is None, answer.fail_detail
    assert answer.flat_dates == 5
    assert answer.metrics is not None


def test_evaluate_node_fails_the_whole_node_when_every_date_is_constant(
    monkeypatch: pytest.MonkeyPatch, context: EvaluationContext
) -> None:
    execution = _execution({day: [5.0, 5.0] for day in _EVAL_DATES})

    answer = _evaluate_with_fixed_execution(monkeypatch, context, execution)

    assert answer.fail_class == "EvaluatorNormalizeError"
    assert answer.metrics is None
    assert "no preference" in (answer.fail_detail or "")
