"""Step 10, run end to end — ``orchestrator._tripwire_step.run_tripwires``.

additions_spec_tripwires_live.xml: *System runs the six leakage tripwires on
every evaluated node between metrics and the ledger debit, so that each node
row returns its perturb_stability and a leaking node returns fail_class
"tripwire_fail".*

Two layers, each with its own claims:

* **the pure sweep** — ``run_tripwires(scores, targets, node_id=...)`` on a
  hand-built panel, with no database and no evaluation context in sight. A
  leak panel rejects on all six probes; a seeded noise panel rejects on
  none; a panel too thin for the perturbation axes answers "not measured"
  for them rather than failing the node; the sweep is deterministic and
  reads no null status, so a "null" node id and a "real" node id given the
  same panel answer the same outcome; and the sweep finishes well inside
  its wall-clock bound at the width the tripwires member's own corpus is
  calibrated against (92 dates, 40 symbols).

* **the wiring** — :func:`orchestrator._evaluate.evaluate_node`, with an
  injected executor standing in for a real sandbox spawn (the same
  duck-typed ``run(code, window, *, seed) -> SandboxResult`` stand-in
  ``test_executor_selection.py`` uses), so the chain runs for real up to and
  through step 10 without a model-authored signal ever executing. A leaking
  executor's node ends ``fail_class="tripwire_fail"``, still debited, still
  row-written (the evidence survives), and poisoned (feature 131); a clean
  executor's node ends ``fail_class=None`` with a non-null
  ``perturb_stability`` on its row.

No test opens a network connection, reads a real credential, or writes
outside a pytest temporary directory.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import importlib.util
import random
import sqlite3
import time
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
from orchestrator._tripwire_step import NOT_MEASURED, PROBE_NAMES, run_tripwires
from snapshot import SnapshotService
from tripwires import LOOKBACK_AXIS, SUBSAMPLE_AXIS, WINDOW_AXIS, stability_of
from tripwires.poison import PoisonStore

# -- The pure sweep: panel builders ---------------------------------------------


def _dates(count: int, *, start: dt.date = dt.date(2024, 1, 1)) -> list[dt.date]:
    return [start + dt.timedelta(days=offset) for offset in range(count)]


def _symbols(count: int) -> list[str]:
    return [f"S{index:02d}" for index in range(count)]


def _gaussian_panel(
    dates: list[dt.date], symbols: list[str], *, seed: int
) -> dict[dt.date, dict[str, float]]:
    """A ``{date: {symbol: value}}`` panel of independent standard normals —
    carries no information about any other panel built from a different seed,
    which is what makes a pairing of two of these a clean (non-leaking)
    candidate against a clean target.
    """
    rng = random.Random(seed)
    return {day: {name: rng.gauss(0.0, 1.0) for name in symbols} for day in dates}


def _leak_panel(
    targets: dict[dt.date, dict[str, float]],
    *,
    date_weight: float = 0.15,
    noise_seed: int,
) -> dict[dt.date, dict[str, float]]:
    """A score panel built to leak on both of step 10's independent probes.

    Two whole-sample statistics of ``targets``, summed: each symbol's
    full-sample mean (the canonical lookahead the time-shuffle probe and the
    four perturbation axes are verified against — a date-independent panel
    statistic a re-dating or a re-run cannot disturb) and a *small* multiple
    of each date's own cross-sectional mean (a date-local, symbol-invariant
    statistic — invariant under any within-date relabelling, since summing a
    permutation's values over all of a date's symbols reproduces the same
    date mean — which is exactly what the label-permutation probe is built
    to catch and the first statistic alone is not, per
    ``TimeShuffleTripwire``'s own docstring: "a whole-sample per-symbol leak
    ... escapes ``label`` and is rejected by ``run``, and a date-local
    cross-sectional leak escapes ``run`` and is caught by ``label``"). Tiny
    per-cell noise keeps every date's cross-section from being perfectly
    tied (``normalize_scores`` would otherwise rank ties by position, not by
    failing — but a hand-fed panel never passes through normalization here,
    and this probe-level test feeds ``run_tripwires`` directly).
    """
    days = sorted(targets)
    symbols = sorted(targets[days[0]])
    mean_of_symbol = {
        symbol: sum(targets[day][symbol] for day in days) / len(days)
        for symbol in symbols
    }
    mean_of_date = {
        day: sum(targets[day][symbol] for symbol in symbols) / len(symbols)
        for day in days
    }
    noise = random.Random(noise_seed)
    return {
        day: {
            symbol: mean_of_symbol[symbol]
            + date_weight * mean_of_date[day]
            + noise.gauss(0.0, 0.001)
            for symbol in symbols
        }
        for day in days
    }


# -- The pure sweep: tests --------------------------------------------------------


def test_a_leak_panel_rejects_on_all_six_probes() -> None:
    dates = _dates(120)
    symbols = _symbols(30)
    targets = {1: _gaussian_panel(dates, symbols, seed=7)}
    scores = _leak_panel(targets[1], noise_seed=99)

    outcome = run_tripwires(scores, targets, node_id="leak-node")

    assert set(outcome.failed) == set(PROBE_NAMES)
    # The lookback axis measured (and rejected) — perturb_stability is the
    # figure it measured, not None; None is reserved for "could not measure"
    # (test_a_too_thin_panel_is_not_measured_not_failed covers that case).
    assert outcome.perturb_stability is not None


def test_a_seeded_noise_panel_rejects_on_none() -> None:
    dates = _dates(92)
    symbols = _symbols(40)
    targets = {1: _gaussian_panel(dates, symbols, seed=1001)}
    scores = _gaussian_panel(dates, symbols, seed=1002)

    outcome = run_tripwires(scores, targets, node_id="clean-node")

    assert outcome.failed == ()
    assert outcome.perturb_stability is not None


def test_a_too_thin_panel_is_not_measured_not_failed() -> None:
    # Three dates, three symbols: wide enough for the two independent probes
    # and the seed axis to measure, too thin for the three axes that need a
    # window with room to offset, subsample or jitter — exactly the split
    # the feature sentence draws between "could not measure" and "failed".
    dates = _dates(3)
    symbols = _symbols(3)
    targets = {1: _gaussian_panel(dates, symbols, seed=3)}
    scores = _gaussian_panel(dates, symbols, seed=4)

    outcome = run_tripwires(scores, targets, node_id="thin-node")

    assert outcome.failed == ()
    assert outcome.perturb_stability is None
    for axis in (WINDOW_AXIS, SUBSAMPLE_AXIS, LOOKBACK_AXIS):
        assert outcome.verdicts[axis] is NOT_MEASURED


def test_run_tripwires_is_deterministic() -> None:
    dates = _dates(30)
    symbols = _symbols(8)
    targets = {1: _gaussian_panel(dates, symbols, seed=11)}
    scores = _gaussian_panel(dates, symbols, seed=12)

    first = run_tripwires(scores, targets, node_id="same-node")
    second = run_tripwires(scores, targets, node_id="same-node")

    assert first.failed == second.failed
    assert first.perturb_stability == second.perturb_stability
    assert first.axis_figures == second.axis_figures
    for name in PROBE_NAMES:
        assert first.verdicts[name] == second.verdicts[name]


def test_a_null_node_and_a_real_node_given_identical_panels_agree() -> None:
    # run_tripwires reads no null status and no sidecar key — it is handed
    # the same scores and the same gated, post-cost targets a null node and
    # a real node are scored on alike, so the only input that can differ
    # between the two calls here is the node id itself, and the outcome
    # must not depend on it beyond the verdicts' own ``node_id`` field.
    dates = _dates(30)
    symbols = _symbols(8)
    targets = {1: _gaussian_panel(dates, symbols, seed=21)}
    scores = _gaussian_panel(dates, symbols, seed=22)

    null_outcome = run_tripwires(scores, targets, node_id="null-node")
    real_outcome = run_tripwires(scores, targets, node_id="real-node")

    assert null_outcome.failed == real_outcome.failed
    assert null_outcome.perturb_stability == real_outcome.perturb_stability
    assert null_outcome.axis_figures == real_outcome.axis_figures
    for name in PROBE_NAMES:
        null_verdict = null_outcome.verdicts[name]
        real_verdict = real_outcome.verdicts[name]
        if null_verdict is NOT_MEASURED:
            assert real_verdict is NOT_MEASURED
            continue
        assert dataclasses.replace(null_verdict, node_id="x") == dataclasses.replace(
            real_verdict, node_id="x"
        )


def test_run_tripwires_wall_time_under_bound() -> None:
    # 92 dates x 40 symbols — the width this module's own docstring measures
    # against (under 5s on this host); asserted at 15s here for slack under
    # pytest-xdist, where this host's cycles are shared with other workers.
    dates = _dates(92)
    symbols = _symbols(40)
    targets = {1: _gaussian_panel(dates, symbols, seed=777)}
    scores = _gaussian_panel(dates, symbols, seed=778)

    start = time.perf_counter()
    run_tripwires(scores, targets, node_id="timing-node")
    elapsed = time.perf_counter() - start

    assert elapsed < 15.0


# -- The wiring: evaluate_node with an injected executor ------------------------

REPO_ROOT = Path(__file__).resolve().parents[3]
VERSIONS_DIR = REPO_ROOT / "migrations" / "versions"
NODE_TABLE_MIGRATIONS = ("0118_node_table", "0114_node_metrics")

SYMBOLS = ("AAA", "BBB", "CCC", "DDD")
FIRST_DAY = dt.date(2026, 9, 1)
LOOKBACK = 10
#: 71 bar days (60 evaluation dates past a 10-bar lookback) — the same width
#: ``test_evaluate.py`` pins for its own momentum journey, for the same
#: reason restated there: the six probes standardize by √T, and a grid
#: narrower than this gives an honest signal (or, here, an honest noise
#: candidate) a real chance of landing a false ``tripwire_fail`` by chance
#: under more than one of the six.
BAR_DAYS = tuple(FIRST_DAY + dt.timedelta(days=offset) for offset in range(71))
EVALUATION_DATES = BAR_DAYS[LOOKBACK : LOOKBACK + 60]
EPOCH_ID = "epoch-tripwire-step"
EVALUATOR_HASH = "ab" * 32
SNAPSHOT_HASH_FALLBACK = "cd" * 32
COST_MODEL_HASH = "ef" * 32
CAMPAIGN_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"

#: A signal with no imports and no behaviour — the injected executor's
#: ``run()`` ignores both the code and the window, so this only needs to
#: pass the import screen that runs before any executor is built (the same
#: idiom ``test_executor_selection.py``'s ``_NEUTRAL_CODE`` uses).
_NEUTRAL_CODE = "def signal(ctx, seed):\n    pass\n"

#: The target bundle's per-symbol fixed effect, plus a small per-day draw —
#: a real (if weak) cross-sectional factor with enough day-to-day motion
#: that a signal's per-date rank correlation varies across the grid (a
#: perfectly constant correlation is itself refused upstream, by
#: ``compute_node_metrics``'s own zero-standard-error guard, before step 10
#: ever runs). Built once, at import, from a fixed seed — determinism, for
#: the reason every other seed in this module is pinned.
def _build_target_bundle() -> dict[dt.date, dict[str, float]]:
    rng = random.Random(20260101)
    base = {symbol: 0.001 * (index + 1) for index, symbol in enumerate(SYMBOLS)}
    return {
        day: {symbol: base[symbol] + rng.gauss(0.0, 0.0003) for symbol in SYMBOLS}
        for day in BAR_DAYS
    }


_TARGET_BUNDLE = _build_target_bundle()


def _load_migration(revision: str) -> ModuleType:
    path = VERSIONS_DIR / f"{revision}.py"
    spec = importlib.util.spec_from_file_location(
        f"_tripwire_step_test_{revision}", path
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


def _metric_columns(database_url: str, node_id: str) -> dict[str, Any]:
    columns = ("ic_mean", "ic_tstat", "ir_standalone", "turnover")
    with closing(sqlite3.connect(_path_of(database_url))) as connection:
        row = connection.execute(
            f"SELECT {', '.join(columns)} FROM node WHERE id = ?", (node_id,)
        ).fetchone()
    assert row is not None, f"the tree lost its row for {node_id!r}"
    return dict(zip(columns, row))


class RecordingEndpoint:
    """A fake ``TargetEndpoint`` answering slices of :data:`_TARGET_BUNDLE`.

    The same stand-in ``test_evaluate.py`` uses — the gate's support check
    certifies honestly against the real alignment's own dates and symbols —
    but the series itself is this module's own precomputed bundle, so a test
    can build an executor's scores from exactly the values the node will be
    gated and priced against.
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
            day: {symbol: _TARGET_BUNDLE[day][symbol] for symbol in symbols}
            for day in days
            if day in _TARGET_BUNDLE
        }
        return TargetResponse(
            status=OK,
            node_id=request.node_id,
            target_series=series,
            charges_budget=self.charges_budget,
        )


def _seal_minimal_snapshot(workdir: Path) -> Any:
    """The smallest sealed snapshot ``resolve_window`` will resolve: one bar
    per symbol per bar day — the injected executor ignores the window's
    contents entirely, so the price is a placeholder, not a fixture under
    test (the same minimality ``test_executor_selection.py``'s own
    ``_seal_minimal_snapshot`` uses, widened to this module's symbols and
    dates).
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
                        "close": ["100.0"],
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
    return _seal_minimal_snapshot(tmp_path_factory.mktemp("tripwire-step-world"))


@pytest.fixture
def context(tmp_path: Path, sealed_snapshot: Any) -> EvaluationContext:
    config = load_cost_model()
    schedule = FeeSchedule(venue=config.venue, taker_bps=10.0, maker_bps=10.0)
    database_url = f"sqlite:///{tmp_path / 'tripwire-step-test.db'}"
    _migrate_tree(database_url)
    closes = {symbol: {day: 100.0 for day in BAR_DAYS} for symbol in SYMBOLS}
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


def _new_node(context: EvaluationContext) -> str:
    node_id = str(uuid.uuid4())
    _plant_root(context.database_url, node_id=node_id, campaign_id=CAMPAIGN_ID)
    return node_id


@dataclasses.dataclass
class _ScriptedExecutor:
    """A duck-typed stand-in for ``signal_sandbox(context)``'s own answer —
    the same ``run(code, window, *, seed)`` shape ``test_executor_selection
    .py``'s ``_FakeExecutor`` uses, except this one answers a real,
    conforming score vector (built by ``score_fn``) rather than a canned
    failure, so the chain runs all the way through metrics and step 10.
    Calls are answered in order against :data:`EVALUATION_DATES` — the same
    order ``execute_signal`` drives rebalance dates in.
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


def _leaking_score_fn() -> Any:
    """Each symbol's full-sample mean of :data:`_TARGET_BUNDLE`, held
    constant across every evaluation date (plus negligible noise) — the
    canonical whole-sample lookahead, restated for the live wiring test:
    see :func:`_leak_panel`'s own docstring for why this statistic is what
    the time-shuffle probe (and, through it, feature 131's poisoning) is
    verified to catch.
    """
    mean_of_symbol = {
        symbol: sum(_TARGET_BUNDLE[day][symbol] for day in EVALUATION_DATES)
        / len(EVALUATION_DATES)
        for symbol in SYMBOLS
    }
    noise = random.Random(555)

    def score_fn(day: dt.date, universe: Any) -> list[float]:
        return [mean_of_symbol[symbol] + noise.gauss(0.0, 1e-6) for symbol in universe]

    return score_fn


def _clean_score_fn(seed: int) -> Any:
    """Independent noise, uncorrelated with the target bundle — an honest
    candidate's stand-in, the same role ``_gaussian_panel`` plays for the
    pure-sweep tests above.
    """
    rng = random.Random(seed)

    def score_fn(day: dt.date, universe: Any) -> list[float]:
        return [rng.gauss(0.0, 1.0) for _ in universe]

    return score_fn


def test_evaluate_node_with_a_leaking_executor_tripwire_fails_and_poisons(
    context: EvaluationContext,
    ledger: TrialLedger,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    node_id = _new_node(context)
    executor = _ScriptedExecutor(_leaking_score_fn())
    monkeypatch.setattr(evaluate_mod, "signal_sandbox", lambda ctx: executor)
    endpoint = RecordingEndpoint(charges_budget=True)
    oracle = SubtreeOracle(endpoint, database_url=context.database_url)

    answer = evaluate_node(
        node_id,
        CAMPAIGN_ID,
        0,
        _NEUTRAL_CODE,
        context=context,
        oracle=oracle,
        ledger=ledger,
    )

    assert answer.fail_class == "tripwire_fail"
    assert answer.score.fail_class == "tripwire_fail"
    assert answer.score.perturb_stability is None
    assert "time-shuffle" in (answer.fail_detail or "")

    # The trial was still debited, and under the node's own charges_budget
    # bit — step 10 ran to completion, so the node is stated, not failed.
    assert answer.debit.appended is True
    assert answer.debit.charge.outcome == "tripwire_fail"
    assert answer.debit.charge.charges_budget == answer.charges_budget

    # The evidence survives: the row is written and its metrics measured.
    assert answer.persistence is not None
    assert answer.persistence.tree_written is True
    columns = _metric_columns(context.database_url, node_id)
    assert columns["ic_mean"] is not None

    # Feature 131's poisoning fired, driven by the time-shuffle rejection.
    assert PoisonStore(context.database_url).is_poisoned(node_id) is True


def test_evaluate_node_with_a_clean_executor_ends_ok_with_perturb_stability(
    context: EvaluationContext,
    ledger: TrialLedger,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    node_id = _new_node(context)
    executor = _ScriptedExecutor(_clean_score_fn(seed=321))
    monkeypatch.setattr(evaluate_mod, "signal_sandbox", lambda ctx: executor)
    endpoint = RecordingEndpoint(charges_budget=True)
    oracle = SubtreeOracle(endpoint, database_url=context.database_url)

    answer = evaluate_node(
        node_id,
        CAMPAIGN_ID,
        0,
        _NEUTRAL_CODE,
        context=context,
        oracle=oracle,
        ledger=ledger,
    )

    assert answer.fail_class is None
    assert answer.score.fail_class is None
    assert answer.score.perturb_stability is not None
    assert answer.fail_detail is None

    assert answer.debit.appended is True
    assert answer.debit.charge.outcome == "ok"

    assert answer.persistence is not None
    assert answer.persistence.tree_written is True

    assert PoisonStore(context.database_url).is_poisoned(node_id) is False

    # Two of the three poolable perturbation axes landed in the stability
    # ledger — the feature's own "unchanged except ... recorded through
    # stability.record_stability" half, on the no-rejection path. The
    # universe-subsample axis is left out of this check deliberately: at
    # this fixture's four-symbol universe, DEFAULT_SUBSAMPLE_FRACTION (0.20)
    # keeps too few symbols for that axis to ever measure, so it is
    # "not measured" here rather than persisted — a fact about this
    # fixture's width, not about the wiring under test.
    for axis in (WINDOW_AXIS, LOOKBACK_AXIS):
        record = stability_of(node_id, axis=axis, database_url=context.database_url)
        assert record.node_id == node_id
