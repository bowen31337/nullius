"""bug_spec_metrics_horizon.xml bug 2 — the config's horizon reaches the metrics.

Campaign 870d4594 was configured ``"horizon": 5`` and its campaign row records
5, yet every node it stored measures horizon-1 metrics: both evaluation chains
align and gate all of :data:`evaluator.HORIZONS`, the oracles answer every
covered horizon, and ``compute_node_metrics`` — which before bug 1 had no
horizon argument at all — reduces over the shortest covered one, always 1.
The configured horizon reached only the forward-return fallback (never sent:
the gate names a horizon in every request) and the campaign row.

The fix under test here gives the evaluation config an optional
``"metrics_horizon"`` key — closed vocabulary ``{"shortest", "configured"}``,
default ``"shortest"`` so every config written before the key exists behaves
byte-for-byte as it always did — and threads
``context.metrics_horizon_value`` (``None`` under ``"shortest"``,
``context.horizon`` under ``"configured"``) into every
``compute_node_metrics`` call ``evaluate_node``, ``evaluate_on_dates`` and
``_gross_ir_tstat`` make.

The chain fixture is ``test_oos_evaluation.py``'s own recipe scaled to the
question: the same sealed AR(1) world and momentum signal, over a grid whose
dates all carry both a 1-day and a 5-day forward window, with a stub oracle
that answers each requested horizon with its *own* ordering — ascending by
symbol at horizon 1, descending at horizon 5 — so a reading at one horizon
cannot be mistaken for a reading at the other: the horizon-5 Spearman of the
momentum scores is exactly the negation of the horizon-1 one, date for date.
The expected per-date coefficients are computed in this file from the world's
own closes, with the same average-rank Pearson arithmetic the evaluator
spells in ``evaluator._decay`` — not read back from the module under test.

No test opens a network connection, reads a real credential, or writes
outside a pytest temporary directory.  It passes under pytest-xdist: no state
lives outside a fixture, and every sqlite file is per-test.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import importlib.util
import json
import math
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path
from types import ModuleType
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from cost_model import FeeSchedule, load_cost_model
from evaluator import OracleResponse
from ledger import TrialLedger
from orchestrator._context import (
    EvaluationConfigError,
    EvaluationContext,
    load_evaluation_context,
)
from orchestrator._evaluate import evaluate_node, evaluate_on_dates
from snapshot import SnapshotService

# conftest-less suite: this file is under packages/orchestrator/tests, so the
# repository root is four parents up.
REPO_ROOT = Path(__file__).resolve().parents[3]
VERSIONS_DIR = REPO_ROOT / "migrations" / "versions"
NODE_TABLE_MIGRATIONS = ("0118_node_table", "0114_node_metrics")

CODE_WORD = "evaluation_config"


# == Part 0: the world, the signal and the oracle ================================


SYMBOLS = ("AAA", "BBB", "CCC", "DDD")
FIRST_DAY = dt.date(2026, 9, 1)
BAR_DAYS = tuple(FIRST_DAY + dt.timedelta(days=offset) for offset in range(80))
LOOKBACK = 10
# Twelve rebalance dates, each carrying every forward window the panel aligns
# (a horizon-20 window from the last of them closes on bar day 41 of 80), so
# the priced panel covers all of HORIZONS and the gate asks the oracle once
# per horizon — the exact shape the live chain runs under.
EVALUATION_DATES = tuple(
    FIRST_DAY + dt.timedelta(days=offset) for offset in range(10, 22)
)
WORLD_SEED = 729301
AUTOCORRELATION = 0.5
CONFIGURED_HORIZON = 5
EPOCH_ID = "epoch-2026-10-20-metrics-horizon"
EVALUATOR_HASH = "ab" * 32
SNAPSHOT_HASH_FALLBACK = "cd" * 32
COST_MODEL_HASH = "ef" * 32
CAMPAIGN_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"

#: The trailing-momentum signal test_oos_evaluation.py's suite uses — at a
#: rebalance date D it reads the ten closes D-9..D, so the score is
#: ``(close[D] - close[D-9]) / close[D-9]`` and is recomputable in this file
#: straight off the world's own closes dict.
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


def _seal_the_world(workdir: Path) -> tuple[Any, dict[str, dict[dt.date, float]]]:
    import random as _random

    lake_root = workdir / "lake"
    (lake_root / "snapshots").mkdir(parents=True)
    staging = lake_root / "staging"
    staging.mkdir()

    generator = _random.Random(WORLD_SEED)
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


def _stub_oracle(request: Any) -> OracleResponse:
    """Answer every requested horizon with that horizon's own ordering.

    Ascending by sorted symbol at horizon 1, descending at horizon 5, its own
    positive slope at every other horizon — so a horizon-5 reading is the
    sign-flip of a horizon-1 one against any fixed score ranking, and no two
    horizons share a series.  Lives on exactly the support
    ``test_oos_evaluation.py``'s own fake endpoint serves (every calendar day
    of the request's range, every requested symbol), which the gate's
    exact-support certification accepts.
    """
    first, last = request.date_range
    days: list[dt.date] = []
    day = first
    while day <= last:
        days.append(day)
        day += dt.timedelta(days=1)
    symbols = sorted(request.symbols)

    def value(symbol: str, index: int, days_in: int) -> float:
        rank = index + 1
        scale = 1.0 + 0.15 * days_in
        if request.horizon == 1:
            return 0.001 * rank * scale
        if request.horizon == CONFIGURED_HORIZON:
            return -0.001 * rank * scale
        return 0.0001 * request.horizon * rank * scale

    series = {
        day: {
            symbol: value(symbol, index, (day - first).days)
            for index, symbol in enumerate(symbols)
        }
        for day in days
    }
    return OracleResponse(target_series=series, charges_budget=True)


def _momentum(closes: dict[str, dict[dt.date, float]]) -> dict[dt.date, dict[str, float]]:
    """The signal's own scores, recomputed off the world's closes.

    Rank-matched to what the sandbox returns for the same date (the score is
    ``(close[D] - close[D-9]) / close[D-9]``), which is all the expected
    coefficients below need: the evaluator's IC is a rank correlation, and
    ``normalize_scores`` is rank-preserving by construction.
    """
    scores: dict[dt.date, dict[str, float]] = {}
    for day in EVALUATION_DATES:
        row: dict[str, float] = {}
        for symbol in SYMBOLS:
            last = closes[symbol][day]
            first = closes[symbol][day - dt.timedelta(days=LOOKBACK - 1)]
            row[symbol] = (last - first) / first
        scores[day] = row
    return scores


def _average_ranks(values: dict[str, float]) -> dict[str, float]:
    """``evaluator._decay._average_ranks`` spelled here, not imported.

    Symbols tying share the mean of the ranks they would have occupied — the
    same arithmetic the estimator pins, restated in this file so the expected
    coefficients are computed independently of the module under test.
    """
    ordered = sorted((value, symbol) for symbol, value in values.items())
    ranks: dict[str, float] = {}
    index = 0
    while index < len(ordered):
        stop = index
        while stop + 1 < len(ordered) and ordered[stop + 1][0] == ordered[index][0]:
            stop += 1
        shared = (index + 1 + stop + 1) / 2.0
        for position in range(index, stop + 1):
            ranks[ordered[position][1]] = shared
        index = stop + 1
    return ranks


def _spearman(scores: dict[str, float], returns: dict[str, float]) -> float:
    symbols = sorted(set(scores) & set(returns))
    score_ranks = _average_ranks({s: scores[s] for s in symbols})
    return_ranks = _average_ranks({s: returns[s] for s in symbols})
    count = float(len(symbols))
    score_mean = math.fsum(score_ranks.values()) / count
    return_mean = math.fsum(return_ranks.values()) / count
    covariance = math.fsum(
        (score_ranks[s] - score_mean) * (return_ranks[s] - return_mean)
        for s in symbols
    )
    score_spread = math.fsum((score_ranks[s] - score_mean) ** 2 for s in symbols)
    return_spread = math.fsum((return_ranks[s] - return_mean) ** 2 for s in symbols)
    return covariance / math.sqrt(score_spread * return_spread)


def _stub_returns(day: dt.date, horizon: int) -> dict[str, float]:
    """The stub oracle's own series for ``day`` at ``horizon``."""
    symbols = sorted(SYMBOLS)
    days_in = (day - EVALUATION_DATES[0]).days
    if horizon == 1:
        return {s: 0.001 * (i + 1) * (1.0 + 0.15 * days_in) for i, s in enumerate(symbols)}
    if horizon == CONFIGURED_HORIZON:
        return {
            s: -0.001 * (i + 1) * (1.0 + 0.15 * days_in) for i, s in enumerate(symbols)
        }
    return {
        s: 0.0001 * horizon * (i + 1) * (1.0 + 0.15 * days_in)
        for i, s in enumerate(symbols)
    }


def _expected_ic_series(
    closes: dict[str, dict[dt.date, float]], horizon: int
) -> dict[dt.date, float]:
    """The per-date Spearman of the momentum scores against the stub's series.

    The venue's turnover charge is a uniform per-date shift, and the stub's
    per-horizon ordering is monotone in the symbol index, so the post-cost
    ranks are the raw series' own ranks — the measured coefficient is exactly
    this one.
    """
    momentum = _momentum(closes)
    return {
        day: _spearman(momentum[day], _stub_returns(day, horizon))
        for day in EVALUATION_DATES
    }


@pytest.fixture(scope="module")
def sealed_world(tmp_path_factory: pytest.TempPathFactory) -> tuple[Any, dict]:
    workdir = tmp_path_factory.mktemp("metrics-horizon-world")
    return _seal_the_world(workdir)


def _make_context(
    tmp_path: Path,
    sealed_world: tuple[Any, dict],
    *,
    metrics_horizon: str | None = None,
) -> EvaluationContext:
    """One context over the sealed world, at the campaign's own horizon 5.

    ``metrics_horizon=None`` builds the pre-fix context — the dataclass's own
    default, whatever that turns out to be — for the byte-for-byte "today's
    numbers" comparisons.
    """
    mount, closes = sealed_world
    config = load_cost_model()
    schedule = FeeSchedule(venue=config.venue, taker_bps=10.0, maker_bps=10.0)
    database_url = f"sqlite:///{tmp_path / 'metrics-horizon-test.db'}"
    _migrate_tree(database_url)
    fields: dict[str, Any] = {
        "snapshot": mount,
        "closes": closes,
        "cost_model": config,
        "cost_schedule": schedule,
        "evaluator_hash": EVALUATOR_HASH,
        "snapshot_hash": SNAPSHOT_HASH_FALLBACK,
        "cost_model_hash": COST_MODEL_HASH,
        "epoch_id": EPOCH_ID,
        "database_url": database_url,
        "artifact_dir": tmp_path / "artifacts",
        "seed": WORLD_SEED,
        "horizon": CONFIGURED_HORIZON,
        "evaluation_dates": EVALUATION_DATES,
        "sandbox_runtime": "unisolated",
    }
    if metrics_horizon is not None:
        fields["metrics_horizon"] = metrics_horizon
    return EvaluationContext(**fields)


# -- The store plumbing every chain test needs -----------------------------------


def _load_migration(revision: str) -> ModuleType:
    path = VERSIONS_DIR / f"{revision}.py"
    if not path.is_file():
        raise AssertionError(f"{revision} is not at {path}")
    spec = importlib.util.spec_from_file_location(
        f"_orchestrator_test_metrics_horizon_{revision}", path
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


# == Part 1: the context field and its derived value =============================


def test_default_context_takes_the_shortest_mode(
    tmp_path: Path, sealed_world: tuple[Any, dict]
) -> None:
    context = _make_context(tmp_path, sealed_world)
    assert context.metrics_horizon == "shortest"
    # The derived value is None — compute_node_metrics keeps its own
    # shortest-covered policy, the pre-fix behaviour every stored number has.
    assert context.metrics_horizon_value is None


def test_configured_mode_resolves_the_horizon_and_shortest_resolves_none(
    tmp_path: Path, sealed_world: tuple[Any, dict]
) -> None:
    shortest = _make_context(tmp_path, sealed_world, metrics_horizon="shortest")
    configured = _make_context(
        tmp_path, sealed_world, metrics_horizon="configured"
    )
    assert shortest.metrics_horizon == "shortest"
    assert shortest.metrics_horizon_value is None
    assert configured.metrics_horizon == "configured"
    assert configured.metrics_horizon_value == CONFIGURED_HORIZON == 5


def test_replace_re_resolves_the_configured_horizon(
    tmp_path: Path, sealed_world: tuple[Any, dict]
) -> None:
    """``dataclasses.replace(context, horizon=h)`` is what ``_oos_ir`` runs.

    Under ``"configured"`` the derived value must follow the new horizon —
    this is what makes the OOS path's re-horizoning reach the metrics.  Under
    ``"shortest"`` it stays ``None`` whatever the horizon says.
    """
    configured = _make_context(tmp_path, sealed_world, metrics_horizon="configured")
    re_horizoned = dataclasses.replace(configured, horizon=10)
    assert re_horizoned.horizon == 10
    assert re_horizoned.metrics_horizon == "configured"
    assert re_horizoned.metrics_horizon_value == 10

    shortest = _make_context(tmp_path, sealed_world, metrics_horizon="shortest")
    assert dataclasses.replace(shortest, horizon=10).metrics_horizon_value is None


# == Part 2: the config key, through the real loader =============================


LOAD_SYMBOLS = ("SYM00", "SYM01", "SYM02")
LOAD_FIRST_DAY = dt.date(2026, 9, 1)
LOAD_BAR_DAYS = tuple(
    LOAD_FIRST_DAY + dt.timedelta(days=offset) for offset in range(14)
)
LOAD_EVALUATION_DAYS = tuple(
    day.isoformat()
    for day in (
        LOAD_BAR_DAYS[3],
        LOAD_BAR_DAYS[4],
        LOAD_BAR_DAYS[5],
        LOAD_BAR_DAYS[6],
    )
)
LOAD_HORIZON = 5
LOAD_SEED = 20261020
LOAD_EPOCH = "epoch-2026-10-20-metrics-horizon-load"
LOAD_IMAGE = "ghcr.io/nullius/evaluator@sha256:" + "ab" * 32
LOAD_VENUE = "testnet_spot_metrics_horizon"
LOAD_VERSION = "2026.10.20"


@pytest.fixture
def load_world(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[dict[str, Any], dict[str, str]]:
    """A minimal, fully configured document and environment for the loader.

    Scaled down from ``test_oos_evaluation.py``'s own ``load_world`` — this
    suite is not re-testing every key, only ``metrics_horizon`` — with the
    horizon set to 5 and an evaluation grid whose last date still carries a
    five-day forward window in the sealed bars.
    """
    monkeypatch.delenv("DATABASE_URL", raising=False)
    lake_root = tmp_path / "lake"
    (lake_root / "snapshots").mkdir(parents=True)
    staging = lake_root / "staging"
    for index, symbol in enumerate(LOAD_SYMBOLS):
        for offset, day in enumerate(LOAD_BAR_DAYS):
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
                        "close": [str(round(100.0 + 10.0 * index + 0.25 * offset, 2))],
                        "volume": ["12.5"],
                    }
                ),
                partition / "part-0.parquet",
            )
    service = SnapshotService(lake_root)
    sealed = service.seal(sealed_at=dt.datetime(2026, 11, 1, tzinfo=dt.UTC))

    cost_model_path = tmp_path / "cost_model.yaml"
    cost_model_path.write_text(
        "cost_model:\n"
        f'  version: "{LOAD_VERSION}"\n'
        f"  venue: {LOAD_VENUE}\n"
        "  fees:\n"
        "    taker_bps: 12.5\n"
        "    maker_bps: 8.0\n",
        encoding="utf-8",
    )

    document: dict[str, Any] = {
        "snapshot_mount": str(sealed.path),
        "evaluation_dates": list(LOAD_EVALUATION_DAYS),
        "horizon": LOAD_HORIZON,
        "seed": LOAD_SEED,
        "epoch_id": LOAD_EPOCH,
        "artifact_dir": str(tmp_path / "artifacts"),
        "sandbox_runtime": "unisolated",
        "acknowledge_unisolated": True,
    }

    bwrap_dir = tmp_path / "bwrap-path"
    bwrap_dir.mkdir()
    bwrap = bwrap_dir / "bwrap"
    bwrap.write_text("#! /bin/sh\n", encoding="utf-8")
    bwrap.chmod(0o755)

    environment = {
        "DATABASE_URL": f"sqlite:///{tmp_path / 'metrics-horizon-load-test.db'}",
        "NULLIUS_EVALUATOR_IMAGE": LOAD_IMAGE,
        "NULLIUS_COST_MODEL_PATH": str(cost_model_path),
        "PATH": str(bwrap_dir),
    }
    return document, environment


def _loaded(
    tmp_path: Path,
    load_world: tuple[dict[str, Any], dict[str, str]],
    **extra: Any,
) -> EvaluationContext:
    document, environment = load_world
    document = dict(document, **extra)
    config_path = tmp_path / f"evaluation-{abs(id(document))}.json"
    config_path.write_text(json.dumps(document), encoding="utf-8")
    environment = dict(environment, NULLIUS_EVALUATION_CONFIG=str(config_path))

    context = load_evaluation_context(environment)
    assert context is not None
    return context


def test_an_absent_key_defaults_to_shortest(
    tmp_path: Path, load_world: tuple[dict[str, Any], dict[str, str]]
) -> None:
    context = _loaded(tmp_path, load_world)
    assert "metrics_horizon" not in load_world[0]
    assert context.metrics_horizon == "shortest"
    assert context.metrics_horizon_value is None


def test_both_modes_parse_and_the_configured_mode_carries_the_horizon(
    tmp_path: Path, load_world: tuple[dict[str, Any], dict[str, str]]
) -> None:
    shortest = _loaded(tmp_path, load_world, metrics_horizon="shortest")
    configured = _loaded(tmp_path, load_world, metrics_horizon="configured")
    assert shortest.metrics_horizon == "shortest"
    assert shortest.metrics_horizon_value is None
    assert configured.metrics_horizon == "configured"
    assert configured.horizon == LOAD_HORIZON == 5
    assert configured.metrics_horizon_value == 5


def test_a_third_spelling_is_refused_by_name(
    tmp_path: Path, load_world: tuple[dict[str, Any], dict[str, str]]
) -> None:
    document, environment = load_world
    document = dict(document, metrics_horizon="native")
    config_path = tmp_path / "evaluation-native.json"
    config_path.write_text(json.dumps(document), encoding="utf-8")
    environment = dict(environment, NULLIUS_EVALUATION_CONFIG=str(config_path))

    with pytest.raises(EvaluationConfigError) as record:
        load_evaluation_context(environment)

    message = str(record.value)
    assert message.startswith(f"{CODE_WORD}:")
    assert "metrics_horizon" in message
    assert "native" in message
    assert "shortest" in message
    assert "configured" in message


# == Part 3: the chain — evaluate_on_dates and evaluate_node ======================


def _assert_metrics_equal_to_1e_12(left: Any, right: Any) -> None:
    """Two NodeMetrics agree byte-for-byte: floats to 1e-12, the rest exactly."""
    assert left.horizon == right.horizon
    assert dict(left.ic_series) == pytest.approx(dict(right.ic_series), abs=1e-12)
    for field in dataclasses.fields(left):
        if field.name == "ic_series":
            continue
        left_value = getattr(left, field.name)
        right_value = getattr(right, field.name)
        if isinstance(left_value, float):
            assert left_value == pytest.approx(right_value, abs=1e-12)
        else:
            assert left_value == right_value


def test_configured_mode_measures_the_five_day_series(
    tmp_path: Path, sealed_world: tuple[Any, dict]
) -> None:
    """The whole point: ``"horizon": 5`` now *scores* at horizon 5.

    Under ``"configured"`` the NodeMetrics carry horizon 5 and an ic_series
    equal to the per-date Spearman of the momentum scores against the stub
    oracle's own 5-day series — computed here, off the world's closes.  Under
    ``"shortest"`` the same call measures horizon 1, the pre-fix reading.
    """
    _, closes = sealed_world
    configured_context = _make_context(
        tmp_path, sealed_world, metrics_horizon="configured"
    )
    shortest_context = _make_context(
        tmp_path, sealed_world, metrics_horizon="shortest"
    )
    default_context = _make_context(tmp_path, sealed_world)
    node_id = _new_node(configured_context)

    configured_metrics, _ = evaluate_on_dates(
        node_id,
        MOMENTUM_SIGNAL_CODE,
        context=configured_context,
        oracle=_stub_oracle,
        dates=EVALUATION_DATES,
    )
    shortest_metrics, _ = evaluate_on_dates(
        node_id,
        MOMENTUM_SIGNAL_CODE,
        context=shortest_context,
        oracle=_stub_oracle,
        dates=EVALUATION_DATES,
    )

    assert configured_metrics.horizon == CONFIGURED_HORIZON == 5
    assert configured_metrics.dates == len(EVALUATION_DATES)
    expected_five_day = _expected_ic_series(closes, CONFIGURED_HORIZON)
    assert dict(configured_metrics.ic_series) == pytest.approx(
        expected_five_day, abs=1e-12
    )
    assert configured_metrics.ic_mean == pytest.approx(
        math.fsum(expected_five_day.values()) / len(expected_five_day), abs=1e-12
    )

    assert shortest_metrics.horizon == 1
    expected_one_day = _expected_ic_series(closes, 1)
    assert dict(shortest_metrics.ic_series) == pytest.approx(
        expected_one_day, abs=1e-12
    )
    # The two horizons genuinely disagree — the stub's orderings are built so
    # a horizon-5 reading cannot be a horizon-1 reading misread.
    assert configured_metrics.ic_mean * shortest_metrics.ic_mean < 0.0

    default_metrics, _ = evaluate_on_dates(
        node_id,
        MOMENTUM_SIGNAL_CODE,
        context=default_context,
        oracle=_stub_oracle,
        dates=EVALUATION_DATES,
    )
    _assert_metrics_equal_to_1e_12(default_metrics, shortest_metrics)


def test_shortest_mode_is_today_to_1e_12(
    tmp_path: Path, sealed_world: tuple[Any, dict]
) -> None:
    """An explicit ``"shortest"`` and the pre-fix default agree to 1e-12."""
    node_id = _new_node(
        _make_context(tmp_path, sealed_world, metrics_horizon="shortest")
    )
    shortest_context = _make_context(
        tmp_path, sealed_world, metrics_horizon="shortest"
    )
    default_context = _make_context(tmp_path, sealed_world)

    shortest_metrics, shortest_ir = evaluate_on_dates(
        node_id,
        MOMENTUM_SIGNAL_CODE,
        context=shortest_context,
        oracle=_stub_oracle,
        dates=EVALUATION_DATES,
    )
    default_metrics, default_ir = evaluate_on_dates(
        node_id,
        MOMENTUM_SIGNAL_CODE,
        context=default_context,
        oracle=_stub_oracle,
        dates=EVALUATION_DATES,
    )
    _assert_metrics_equal_to_1e_12(shortest_metrics, default_metrics)
    assert shortest_ir == pytest.approx(default_ir, abs=1e-12)


def test_the_gross_diagnostic_measures_the_same_horizon_as_the_net_figure(
    tmp_path: Path, sealed_world: tuple[Any, dict]
) -> None:
    """``ir_tstat_gross`` follows the configured horizon too.

    The stub's horizon-5 ordering is the sign-flip of its horizon-1 one, so a
    gross figure measured over the wrong horizon would carry the wrong sign —
    here both readings must be negative under ``"configured"`` and positive
    under ``"shortest"``, and they must differ.
    """
    node_id = _new_node(
        _make_context(tmp_path, sealed_world, metrics_horizon="configured")
    )
    configured_context = _make_context(
        tmp_path, sealed_world, metrics_horizon="configured"
    )
    shortest_context = _make_context(
        tmp_path, sealed_world, metrics_horizon="shortest"
    )

    configured = evaluate_on_dates(
        node_id,
        MOMENTUM_SIGNAL_CODE,
        context=configured_context,
        oracle=_stub_oracle,
        dates=EVALUATION_DATES,
    )
    shortest = evaluate_on_dates(
        node_id,
        MOMENTUM_SIGNAL_CODE,
        context=shortest_context,
        oracle=_stub_oracle,
        dates=EVALUATION_DATES,
    )
    assert configured.ir_tstat_gross != pytest.approx(shortest.ir_tstat_gross)
    assert configured.ir_tstat_gross < 0.0 < shortest.ir_tstat_gross


def test_evaluate_node_stamps_the_configured_horizon(
    tmp_path: Path, sealed_world: tuple[Any, dict]
) -> None:
    """The in-sample chain stamps the same horizon the config names."""
    _, closes = sealed_world
    configured_context = _make_context(
        tmp_path, sealed_world, metrics_horizon="configured"
    )
    node_id = _new_node(configured_context)
    ledger = TrialLedger(configured_context.database_url)

    answer = evaluate_node(
        node_id,
        CAMPAIGN_ID,
        0,
        MOMENTUM_SIGNAL_CODE,
        context=configured_context,
        oracle=_stub_oracle,
        ledger=ledger,
    )

    assert answer.fail_class is None, answer.fail_detail
    assert answer.metrics is not None
    assert answer.metrics.horizon == CONFIGURED_HORIZON == 5
    expected_five_day = _expected_ic_series(closes, CONFIGURED_HORIZON)
    assert dict(answer.metrics.ic_series) == pytest.approx(
        expected_five_day, abs=1e-12
    )
    assert answer.debit.appended is True


def test_evaluate_node_under_shortest_keeps_today_numbers(
    tmp_path: Path, sealed_world: tuple[Any, dict]
) -> None:
    """``evaluate_node`` without the key measures horizon 1, as it always did."""
    shortest_context = _make_context(
        tmp_path, sealed_world, metrics_horizon="shortest"
    )
    default_context = _make_context(tmp_path, sealed_world)
    node_id = _new_node(shortest_context)
    ledger = TrialLedger(shortest_context.database_url)

    shortest_answer = evaluate_node(
        node_id,
        CAMPAIGN_ID,
        0,
        MOMENTUM_SIGNAL_CODE,
        context=shortest_context,
        oracle=_stub_oracle,
        ledger=ledger,
    )
    # The same node under the pre-fix default context — a re-evaluation,
    # which the chain supports (the node row and verdicts refresh), so the
    # comparison carries the same node identity on both sides.
    default_answer = evaluate_node(
        node_id,
        CAMPAIGN_ID,
        0,
        MOMENTUM_SIGNAL_CODE,
        context=default_context,
        oracle=_stub_oracle,
        ledger=ledger,
    )

    assert shortest_answer.metrics is not None
    assert shortest_answer.metrics.horizon == 1
    assert default_answer.metrics is not None
    assert default_answer.metrics.horizon == 1
    _assert_metrics_equal_to_1e_12(shortest_answer.metrics, default_answer.metrics)
