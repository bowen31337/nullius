"""M1's tripwire exit, proved on a sealed snapshot — a leaking signal is
caught by every probe, through the real wired pipeline.

additions_spec_tripwires_live.xml, "Tripwires in the Live Pipeline", feature
3: *System proves M1's tripwire exit on a sealed snapshot, so that the
acceptance gate returns a failure if any tripwire stops catching a
deliberately leaking signal.*

This module builds one sealed snapshot of daily bars — 40 symbols, 120
days, from a seeded random walk — and evaluates three candidates through
:func:`orchestrator._evaluate.evaluate_node` with an injected stub executor
(the same ``run(code, window, *, seed) -> SandboxResult`` stand-in
``packages/orchestrator/tests/test_tripwire_step.py`` uses), never the real
sandbox:

* a leaking signal whose score is the next day's return — every one of the
  six leakage probes (:mod:`orchestrator._tripwire_step`) rejects it, and
  the node ends ``fail_class="tripwire_fail"``;
* a lagged leak (the return two days ahead) — weaker, but still caught by
  at least the time-shuffle and label-permute probes;
* an honest 20-day trailing momentum signal, which reads only the past — no
  probe rejects it, and its ``perturb_stability`` is a finite number.

Both leaking candidates are built from two components, because the module's
own docstring states the probes are complementary rather than redundant
(time-shuffle catches a whole-sample, per-symbol statistic; label-permute
catches a same-date, cross-sectional one; neither is the other's superset):
a whole-sample mean of the forward return in question, held constant across
every rebalance date, and the actual, same-date forward return itself. The
scores the stub executor returns are *raw* — they run through the real
pipeline's own :func:`evaluator.normalize_scores` (rank, then z-score, per
date) before :mod:`orchestrator._tripwire_step` ever sees them, which erases
any component that is merely a shared shift across one date's symbols; the
two components above are the ones that survive that normalization. The
exact weights below (10x whole-sample to 1x same-date for the next-day leak,
20x to 1x for the two-day one) and the market's own seed are pinned because
they were measured, empirically, against this fixture's exact width (40
symbols, 98 scored dates after a 20-day lookback) to clear every probe's own
threshold with margin — a different width or a different seed is a
different measurement, which is why both are literals here rather than
knobs.

The planted-leak corpus (:mod:`tripwires.corpus`) is run through the same
:func:`orchestrator._tripwire_step.run_tripwires` sweep directly, asserting
feature 133's own guarantee (0 escapes) holds through this member's seam
too.

No test opens a network connection, reads a real credential, or writes
outside a pytest temporary directory.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import importlib.util
import math
import random
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
from evaluator import SandboxResult
from ledger import TrialLedger
from nulloracle.target import OK, TargetResponse
from orchestrator import _evaluate as evaluate_mod
from orchestrator._context import EvaluationContext
from orchestrator._evaluate import evaluate_node
from orchestrator._oracle import SubtreeOracle
from orchestrator._tripwire_step import PROBE_NAMES, run_tripwires
from snapshot import SnapshotService
from tripwires import LABEL_PERMUTE_NAME, TIME_SHUFFLE_NAME
from tripwires.corpus import planted_signals

REPO_ROOT = Path(__file__).resolve().parents[2]
VERSIONS_DIR = REPO_ROOT / "migrations" / "versions"
NODE_TABLE_MIGRATIONS = ("0118_node_table", "0114_node_metrics")

# -- The sealed world: 40 symbols, 120 days, a seeded random walk --------------

SYMBOLS = tuple(f"S{index:02d}" for index in range(40))
FIRST_DAY = dt.date(2026, 2, 1)
BAR_DAYS = tuple(FIRST_DAY + dt.timedelta(days=offset) for offset in range(120))
_DAY_INDEX = {day: index for index, day in enumerate(BAR_DAYS)}

#: The lookback a 20-day momentum signal needs before its first scored date,
#: and the trailing room (2 bar days) a two-day-ahead leak needs after its
#: last one — together they bound the 98 dates actually scored.
LOOKBACK = 20
EVALUATION_DATES = BAR_DAYS[LOOKBACK : len(BAR_DAYS) - 2]

#: The market's one seed. Independent, zero-drift daily returns (a plain
#: random walk — no persistent per-symbol edge, so the honest momentum
#: candidate below has nothing but noise to find) over which the two
#: leaking candidates and the corpus check are measured.
MARKET_SEED = 24

EPOCH_ID = "epoch-leaking-signal-caught"
EVALUATOR_HASH = "ab" * 32
SNAPSHOT_HASH_FALLBACK = "cd" * 32
COST_MODEL_HASH = "ef" * 32
CAMPAIGN_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"

#: A signal with no imports and no behaviour — the injected executor's
#: ``run()`` ignores both the code and the window, so this only needs to
#: pass the import screen that runs before any executor is built.
_NEUTRAL_CODE = "def signal(ctx, seed):\n    pass\n"

#: Case (a)'s weights: a whole-sample mean of the next day's return (a
#: date-invariant, per-symbol statistic) plus the actual next-day return
#: itself (a same-date, cross-sectional one) — measured to clear all six
#: probes' bars at this fixture's width.
_CASE_A_WHOLE_SAMPLE_WEIGHT = 10.0
_CASE_A_SAME_DATE_WEIGHT = 1.0

#: Case (b)'s weights, over the two-day-ahead compound return instead —
#: measured to clear at least the time-shuffle and label-permute bars.
_CASE_B_WHOLE_SAMPLE_WEIGHT = 20.0
_CASE_B_SAME_DATE_WEIGHT = 1.0


#: The walk's daily volatility — small enough that compounding it over 120
#: days keeps every price positive. The tripwire probes read scores through
#: ``normalize_scores`` (rank, then z-score) and verdicts off a Sharpe
#: ratio, both scale-invariant, so this figure is cosmetic: it does not
#: change which probes reject any of the three cases below, only whether
#: the sealed bars stay a crossable, positive-price walk.
_DAILY_SIGMA = 0.02


def _build_market() -> dict[dt.date, dict[str, float]]:
    """One independent daily return per bar day and symbol — the walk."""
    rng = random.Random(MARKET_SEED)
    return {
        day: {symbol: rng.gauss(0.0, _DAILY_SIGMA) for symbol in SYMBOLS}
        for day in BAR_DAYS
    }


_RET = _build_market()


def _build_prices() -> dict[dt.date, dict[str, float]]:
    """The random walk's own price level — ``_RET`` compounded from a base of 100.

    The sealed snapshot's bars and ``EvaluationContext.closes`` both carry
    this series (never the raw ``_RET`` panel directly): the daily bars are
    a genuine random walk, in the literal sense the spec's own words name,
    and ``close[day+1] / close[day] - 1`` reproduces ``_RET`` exactly.
    """
    prices: dict[dt.date, dict[str, float]] = {BAR_DAYS[0]: dict.fromkeys(SYMBOLS, 100.0)}
    previous = BAR_DAYS[0]
    for day in BAR_DAYS[1:]:
        prices[day] = {
            symbol: prices[previous][symbol] * (1.0 + _RET[day][symbol])
            for symbol in SYMBOLS
        }
        previous = day
    return prices


_PRICES = _build_prices()


def _next_day_return(day: dt.date, symbol: str) -> float:
    """The actual return realized the day after ``day`` — the horizon-1 target."""
    return _RET[BAR_DAYS[_DAY_INDEX[day] + 1]][symbol]


def _two_day_compound_return(day: dt.date, symbol: str) -> float:
    """The compound return realized two days after ``day``."""
    index = _DAY_INDEX[day]
    return (1.0 + _RET[BAR_DAYS[index + 1]][symbol]) * (
        1.0 + _RET[BAR_DAYS[index + 2]][symbol]
    ) - 1.0


def _trailing_momentum(day: dt.date, symbol: str) -> float:
    """The trailing 20-day sum of past returns — reads only what came before ``day``."""
    index = _DAY_INDEX[day]
    return sum(_RET[BAR_DAYS[index - lag]][symbol] for lag in range(1, 21))


#: Each symbol's own average next-day (resp. two-day) return, over every
#: scored date — a whole-sample statistic that is the same number on every
#: rebalance date, the look-ahead a time-shuffle re-dating cannot disturb.
_MEAN_NEXT_DAY = {
    symbol: sum(_next_day_return(day, symbol) for day in EVALUATION_DATES)
    / len(EVALUATION_DATES)
    for symbol in SYMBOLS
}
_MEAN_TWO_DAY = {
    symbol: sum(_two_day_compound_return(day, symbol) for day in EVALUATION_DATES)
    / len(EVALUATION_DATES)
    for symbol in SYMBOLS
}


def _leaking_next_day_score_fn() -> Any:
    """Case (a): a whole-sample mean of the next day's return, plus the return itself."""

    def score_fn(day: dt.date, universe: Any) -> list[float]:
        return [
            _CASE_A_WHOLE_SAMPLE_WEIGHT * _MEAN_NEXT_DAY[symbol]
            + _CASE_A_SAME_DATE_WEIGHT * _next_day_return(day, symbol)
            for symbol in universe
        ]

    return score_fn


def _lagged_two_day_score_fn() -> Any:
    """Case (b): the same construction, one day further ahead and more diluted."""

    def score_fn(day: dt.date, universe: Any) -> list[float]:
        return [
            _CASE_B_WHOLE_SAMPLE_WEIGHT * _MEAN_TWO_DAY[symbol]
            + _CASE_B_SAME_DATE_WEIGHT * _two_day_compound_return(day, symbol)
            for symbol in universe
        ]

    return score_fn


def _honest_momentum_score_fn() -> Any:
    """Case (c): a genuine, backward-looking momentum signal — no look-ahead at all."""

    def score_fn(day: dt.date, universe: Any) -> list[float]:
        return [_trailing_momentum(day, symbol) for symbol in universe]

    return score_fn


# -- The sealed snapshot: one bar per symbol per day, placeholder prices -------


def _seal_minimal_snapshot(workdir: Path) -> Any:
    """The sealed snapshot ``resolve_window`` will resolve — one real random-walk bar
    per symbol per bar day.

    The injected executors above ignore the window's contents entirely
    (they score off the fixture's own seeded market directly, never the
    sealed bytes), so the price is not itself a fixture under test — but it
    is the same ``_PRICES`` walk the leaks and the honest signal are scored
    against, not an unrelated placeholder.
    """
    lake_root = workdir / "lake"
    (lake_root / "snapshots").mkdir(parents=True)
    staging = lake_root / "staging"
    staging.mkdir()
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
                        "close": [str(_PRICES[day][symbol])],
                        "volume": ["1.0"],
                    }
                ),
                partition / "part-0.parquet",
            )
    service = SnapshotService(lake_root)
    sealed = service.seal(sealed_at=dt.datetime(2026, 11, 1, tzinfo=dt.UTC))
    return service.mount(sealed.name)


@pytest.fixture(scope="module")
def sealed_snapshot(tmp_path_factory: pytest.TempPathFactory) -> Any:
    return _seal_minimal_snapshot(tmp_path_factory.mktemp("leaking-signal-world"))


# -- The tree: migrations, a fresh node per test -------------------------------


def _load_migration(revision: str) -> ModuleType:
    path = VERSIONS_DIR / f"{revision}.py"
    spec = importlib.util.spec_from_file_location(
        f"_leaking_signal_test_{revision}", path
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


def _new_node(context: EvaluationContext) -> str:
    node_id = str(uuid.uuid4())
    _plant_root(context.database_url, node_id=node_id, campaign_id=CAMPAIGN_ID)
    return node_id


def _tripwire_verdict_rows(database_url: str, node_id: str) -> dict[str, int]:
    """``{probe: rejected}`` off :data:`orchestrator._evaluate.TRIPWIRE_VERDICT_TABLE`
    for ``node_id`` — the row step 10 persists per probe, win or lose.
    """
    with closing(sqlite3.connect(_path_of(database_url))) as connection:
        rows = connection.execute(
            f"SELECT probe, rejected FROM {evaluate_mod.TRIPWIRE_VERDICT_TABLE} "
            "WHERE node_id = ?",
            (node_id,),
        ).fetchall()
    return {probe: rejected for probe, rejected in rows}


@pytest.fixture
def context(tmp_path: Path, sealed_snapshot: Any) -> EvaluationContext:
    config = load_cost_model()
    schedule = FeeSchedule(venue=config.venue, taker_bps=10.0, maker_bps=10.0)
    database_url = f"sqlite:///{tmp_path / 'leaking-signal-test.db'}"
    _migrate_tree(database_url)
    closes = {symbol: {day: _PRICES[day][symbol] for day in BAR_DAYS} for symbol in SYMBOLS}
    return EvaluationContext(
        snapshot=sealed_snapshot,
        closes=closes,
        cost_model=config,
        cost_schedule=schedule,
        evaluator_hash=EVALUATOR_HASH,
        snapshot_hash=SNAPSHOT_HASH_FALLBACK,
        cost_model_hash=COST_MODEL_HASH,
        epoch_id=EPOCH_ID,
        database_url=database_url,
        artifact_dir=tmp_path / "artifacts",
        seed=1,
        horizon=1,
        evaluation_dates=EVALUATION_DATES,
        sandbox_runtime="unisolated",
    )


@pytest.fixture
def ledger(context: EvaluationContext) -> TrialLedger:
    return TrialLedger(context.database_url)


# -- The oracle: answers the fixture's own seeded next-day return --------------


class RecordingEndpoint:
    """A fake ``TargetEndpoint`` answering the fixture's own next-day returns.

    Every horizon the gate asks about is answered off the same next-day
    series — the same stand-in ``test_tripwire_step.py`` uses its own
    bundle for — since only the shortest covered horizon (1) ever reaches
    the metrics or the tripwire sweep downstream.
    """

    def __init__(self, *, charges_budget: bool = True) -> None:
        self.charges_budget = charges_budget
        self.requests: list[Any] = []

    def post(self, request: Any) -> TargetResponse:
        self.requests.append(request)
        first, last = request.date_range
        days: list[dt.date] = []
        day = first
        while day <= last:
            days.append(day)
            day += dt.timedelta(days=1)
        symbols = sorted(request.symbols)
        series = {
            day: {symbol: _next_day_return(day, symbol) for symbol in symbols}
            for day in days
            if day in _DAY_INDEX and _DAY_INDEX[day] + 1 < len(BAR_DAYS)
        }
        return TargetResponse(
            status=OK,
            node_id=request.node_id,
            target_series=series,
            charges_budget=self.charges_budget,
        )


@dataclasses.dataclass
class _ScriptedExecutor:
    """A duck-typed stand-in for ``signal_sandbox(context)``'s own answer.

    Answers a real, conforming score vector (built by ``score_fn``) in
    order against :data:`EVALUATION_DATES`, so the chain runs all the way
    through metrics and step 10 without a model-authored signal ever
    executing.
    """

    score_fn: Any
    calls: int = 0
    last_result: SandboxResult | None = None

    def run(self, code: str, window: object, *, seed: int) -> SandboxResult:
        day = EVALUATION_DATES[self.calls]
        self.calls += 1
        values = self.score_fn(day, window.universe)
        result = SandboxResult(
            scores=pl.Series(values, dtype=pl.Float64),
            problems=[],
            fail_class=None,
            detail="",
            seed=seed,
            contract_version="",
        )
        self.last_result = result
        return result


def _evaluate_candidate(
    context: EvaluationContext,
    ledger: TrialLedger,
    monkeypatch: pytest.MonkeyPatch,
    score_fn: Any,
) -> Any:
    node_id = _new_node(context)
    executor = _ScriptedExecutor(score_fn)
    monkeypatch.setattr(evaluate_mod, "signal_sandbox", lambda ctx: executor)
    endpoint = RecordingEndpoint(charges_budget=True)
    oracle = SubtreeOracle(endpoint, database_url=context.database_url)
    return evaluate_node(
        node_id,
        CAMPAIGN_ID,
        0,
        _NEUTRAL_CODE,
        context=context,
        oracle=oracle,
        ledger=ledger,
    )


# -- The three cases ------------------------------------------------------------


def test_a_leaking_signal_whose_score_is_the_next_day_return_fails_every_probe(
    context: EvaluationContext,
    ledger: TrialLedger,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # bug_spec_tripwires_hard_fail: a step-10 rejection is recorded and
    # flagged (tripwires_failed, the tripwire_verdict rows), never a node
    # failure, so M1's exit is asserted through those rather than fail_class.
    answer = _evaluate_candidate(
        context, ledger, monkeypatch, _leaking_next_day_score_fn()
    )

    assert answer.fail_class is None
    assert answer.score.fail_class is None

    missing = [name for name in PROBE_NAMES if name not in answer.tripwires_failed]
    assert missing == [], (
        f"the next-day-return leak escaped {missing}; every one of the six "
        f"probes must reject it (tripwires_failed: {answer.tripwires_failed!r})"
    )

    rejected = _tripwire_verdict_rows(context.database_url, answer.node_id)
    assert set(rejected) == set(PROBE_NAMES)
    assert all(rejected[name] == 1 for name in PROBE_NAMES), rejected


def test_a_lagged_leak_using_the_return_two_days_ahead_is_still_caught(
    context: EvaluationContext,
    ledger: TrialLedger,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answer = _evaluate_candidate(
        context, ledger, monkeypatch, _lagged_two_day_score_fn()
    )

    assert answer.fail_class is None
    assert TIME_SHUFFLE_NAME in answer.tripwires_failed, answer.tripwires_failed
    assert LABEL_PERMUTE_NAME in answer.tripwires_failed, answer.tripwires_failed

    rejected = _tripwire_verdict_rows(context.database_url, answer.node_id)
    assert rejected[TIME_SHUFFLE_NAME] == 1
    assert rejected[LABEL_PERMUTE_NAME] == 1


def test_an_honest_twenty_day_momentum_signal_passes_clean(
    context: EvaluationContext,
    ledger: TrialLedger,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answer = _evaluate_candidate(
        context, ledger, monkeypatch, _honest_momentum_score_fn()
    )

    assert answer.fail_class is None
    assert answer.fail_detail is None
    assert answer.score.fail_class is None
    assert answer.score.perturb_stability is not None
    assert math.isfinite(answer.score.perturb_stability)
    assert answer.tripwires_failed == ()


# -- The planted-leak corpus: 0 escapes, through this same sweep ---------------


def test_the_planted_leak_corpus_scores_zero_escapes_through_run_tripwires() -> None:
    escaped = [
        signal.leak_kind
        for signal in planted_signals()
        if not run_tripwires(signal.scores, signal.targets, node_id=signal.node_id).failed
    ]
    assert escaped == [], f"the planted-leak corpus escaped on: {escaped}"
