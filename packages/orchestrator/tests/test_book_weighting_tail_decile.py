"""The ``"tail_decile"`` research book, from the evaluation config to the chain.

System reads a third ``book.weighting`` setting from the evaluation config —
``"tail_decile"`` — under which each date's research book is long the top
decile of that date's scores and short the bottom decile, equal-weight within
each leg, dollar-neutral and gross 1, with the beta-neutral rescale applied
after, so that a ranking whose return gradient lives in its tails is traded
where the gradient is rather than spread proportionally over the deciles that
carry none.

Two groups of tests, over tmp sealed snapshots throughout:

* **the config** — :data:`orchestrator._context.BOOK_KEY`'s closed vocabulary
  gains ``"tail_decile"`` (:data:`orchestrator._context.TAIL_DECILE_WEIGHTING`)
  beside ``"z"`` and ``"inverse_vol"``; the value parses through
  :func:`~orchestrator._context.load_evaluation_context` — the real public
  seam, over a genuine sealed lake — and an unknown spelling is still refused
  by name, with the refusal now naming all three weightings.
* **the wiring** — :func:`orchestrator._evaluate.evaluate_node` hands
  ``weighting=context.book.weighting`` to every ``compute_node_metrics`` call
  it makes (the net figure and the gross diagnostic alike), so each date's
  book is exactly
  ``book_weights(scores, betas, weighting="tail_decile")`` for that date, and
  the record carries ``tail_k`` — the names each leg held.  It passes no
  ``vols`` (the tail-decile book is a function of the scores alone), and a
  cross-section too small to hold two non-empty deciles is refused for that
  date, the message naming the date and the count.

No test opens a network connection, reads a real credential, or writes
outside a pytest temporary directory. Runs under pytest-xdist: every fixture
builds a fresh temporary database and lake, with no shared module-level
mutable state across tests.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import math
import random
import sqlite3
import uuid
from collections.abc import Mapping
from contextlib import closing
from pathlib import Path
from types import ModuleType
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from cost_model import FeeSchedule, load_cost_model
from evaluator import EvaluatorMetricsError, book_weights
from ledger import TrialLedger
from nulloracle.target import OK, TargetResponse
from orchestrator._context import (
    INVERSE_VOL_WEIGHTING,
    TAIL_DECILE_WEIGHTING,
    Z_WEIGHTING,
    BookConfig,
    EvaluationConfigError,
    EvaluationContext,
    load_evaluation_context,
)
from orchestrator._evaluate import evaluate_node
from orchestrator._oracle import SubtreeOracle
from snapshot import SnapshotService

# conftest-less suite: this file is under packages/orchestrator/tests, so the
# repository root is three parents up.
REPO_ROOT = Path(__file__).resolve().parents[3]
VERSIONS_DIR = REPO_ROOT / "migrations" / "versions"

CODE_WORD = "evaluation_config"


# == Part A: the config, through load_evaluation_context ========================

PART_A_SYMBOLS = ("SYM00", "SYM01")
PART_A_FIRST_DAY = dt.date(2026, 9, 1)
PART_A_BAR_DAYS = tuple(
    PART_A_FIRST_DAY + dt.timedelta(days=offset) for offset in range(12)
)
PART_A_EVALUATION_DAYS = tuple(day.isoformat() for day in PART_A_BAR_DAYS[6:10])


def _part_a_close(symbol_index: int, day_index: int) -> float:
    return round(100.0 + 10.0 * symbol_index + 0.25 * day_index, 2)


def _stage_and_seal_part_a(lake_root: Path) -> Any:
    (lake_root / "snapshots").mkdir(parents=True)
    staging = lake_root / "staging"
    for index, symbol in enumerate(PART_A_SYMBOLS):
        for offset, day in enumerate(PART_A_BAR_DAYS):
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
                        "close": [str(_part_a_close(index, offset))],
                        "volume": ["12.5"],
                    }
                ),
                partition / "part-0.parquet",
            )
    service = SnapshotService(lake_root)
    return service.seal(sealed_at=dt.datetime(2026, 11, 1, tzinfo=dt.UTC))


@pytest.fixture
def document_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[dict[str, Any], dict[str, str]]:
    """One valid base document and environment, pointing at a real sealed lake."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    sealed = _stage_and_seal_part_a(tmp_path / "lake")

    cost_model_path = tmp_path / "cost_model.yaml"
    cost_model_path.write_text(
        'cost_model:\n  version: "2026.10.0"\n  venue: testnet_spot\n'
        "  fees:\n    taker_bps: 12.5\n    maker_bps: 8.0\n",
        encoding="utf-8",
    )

    bwrap_dir = tmp_path / "bin"
    bwrap_dir.mkdir()
    bwrap = bwrap_dir / "bwrap"
    bwrap.write_text("#! /bin/sh\n", encoding="utf-8")
    bwrap.chmod(0o755)

    document: dict[str, Any] = {
        "snapshot_mount": str(sealed.path),
        "evaluation_dates": list(PART_A_EVALUATION_DAYS),
        "horizon": 1,
        "seed": 20261019,
        "epoch_id": "epoch-2026-10-19-tail-decile",
        "artifact_dir": str(tmp_path / "artifacts"),
        "sandbox_runtime": "unisolated",
        "acknowledge_unisolated": True,
    }
    environment = {
        "DATABASE_URL": f"sqlite:///{tmp_path / 'ctx.db'}",
        "NULLIUS_EVALUATOR_IMAGE": "ghcr.io/nullius/evaluator@sha256:" + "ab" * 32,
        "NULLIUS_COST_MODEL_PATH": str(cost_model_path),
        "PATH": str(bwrap_dir),
    }
    return document, environment


def _load(
    document: Mapping[str, Any],
    environment: Mapping[str, str],
    tmp_path: Path,
    name: str,
) -> EvaluationContext | None:
    path = tmp_path / f"evaluation-{name}.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    env = dict(environment)
    env["NULLIUS_EVALUATION_CONFIG"] = str(path)
    return load_evaluation_context(env)


def _refuses(
    document: Mapping[str, Any],
    environment: Mapping[str, str],
    tmp_path: Path,
    name: str,
    *needles: str,
) -> str:
    with pytest.raises(EvaluationConfigError) as record:
        _load(document, environment, tmp_path, name)
    message = str(record.value)
    assert message.startswith(f"{CODE_WORD}:"), message
    for needle in needles:
        assert needle in message, (needle, message)
    return message


def test_tail_decile_weighting_parses(
    document_env: tuple[dict[str, Any], dict[str, str]], tmp_path: Path
) -> None:
    document, environment = document_env
    document = dict(
        document,
        book={"beta_neutral": False, "weighting": TAIL_DECILE_WEIGHTING},
    )
    context = _load(document, environment, tmp_path, "tail-decile")
    assert isinstance(context, EvaluationContext)
    assert context.book.weighting == TAIL_DECILE_WEIGHTING


def test_tail_decile_parses_beside_beta_neutral(
    document_env: tuple[dict[str, Any], dict[str, str]], tmp_path: Path
) -> None:
    """The two knobs are independent, exactly as the other weightings' are:
    a tail-decile book can be beta-neutral too."""
    document, environment = document_env
    document = dict(
        document,
        book={
            "beta_neutral": True,
            "beta_window_days": 20,
            "weighting": TAIL_DECILE_WEIGHTING,
        },
    )
    context = _load(document, environment, tmp_path, "tail-decile-neutral")
    assert isinstance(context, EvaluationContext)
    assert context.book.weighting == TAIL_DECILE_WEIGHTING
    assert context.book.beta_neutral is True


def test_tail_decile_of_the_wrong_type_is_still_refused(
    document_env: tuple[dict[str, Any], dict[str, str]], tmp_path: Path
) -> None:
    document, environment = document_env
    document = dict(document, book={"beta_neutral": False, "weighting": 3})
    _refuses(document, environment, tmp_path, "tail-decile-int", "weighting")


def test_unknown_weighting_is_refused_naming_all_three(
    document_env: tuple[dict[str, Any], dict[str, str]], tmp_path: Path
) -> None:
    """The closed vocabulary grew by one, and the refusal names every member
    of it — a reader who mistyped the new spelling is told what was expected."""
    document, environment = document_env
    document = dict(
        document, book={"beta_neutral": False, "weighting": "tail_decil"}
    )
    message = _refuses(
        document, environment, tmp_path, "unknown-tail-decile", "tail_decil"
    )
    assert Z_WEIGHTING in message
    assert INVERSE_VOL_WEIGHTING in message
    assert TAIL_DECILE_WEIGHTING in message


# == Part B: the wiring, through evaluate_node ==================================

NODE_TABLE_MIGRATIONS = ("0118_node_table", "0114_node_metrics")

BENCHMARK = "BTCUSDT"
PART_B_FIRST_DAY = dt.date(2026, 4, 1)
PART_B_BAR_DAYS = tuple(
    PART_B_FIRST_DAY + dt.timedelta(days=offset) for offset in range(100)
)
EVALUATION_DATES = PART_B_BAR_DAYS[40:80]
HORIZON = 1
WORLD_SEED = 20261019
EPOCH_ID = "epoch-2026-10-19-tail-decile-wiring"
EVALUATOR_HASH = "ab" * 32
SNAPSHOT_HASH_FALLBACK = "cd" * 32
COST_MODEL_HASH = "ef" * 32
CAMPAIGN_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"

#: How many symbols the priced universe carries.  The tail-decile book holds
#: ``floor(n/10)`` names per leg, so a fixture needs at least twenty priced
#: names for the book to exist at all; twenty-four gives ``k = 2`` and leaves
#: the middle two deciles empty, which is what makes this book different from
#: the z-weighted one over the same scores.
PART_B_SYMBOL_COUNT = 24
#: Fewer than twenty names: every date's cross-section is too thin for two
#: non-empty deciles, so the whole evaluation is refused naming the date.
THIN_SYMBOL_COUNT = 12

#: test_book_beta_neutral.py's own momentum signal: it re-ranks symbols by
#: trailing return every rebalance date, so the per-date information
#: coefficient actually varies (a signal whose score never changes gives a
#: constant IC across every date, which compute_node_metrics itself refuses
#: as an undefined t-statistic) and the cross-section moves date to date.
LOOKBACK = 10
WEIGHTING_SIGNAL_CODE = f"""
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
        f"_orchestrator_test_tail_decile_{revision}", path
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


def _seal_world(
    workdir: Path,
    *,
    symbol_count: int,
) -> tuple[Any, dict[str, dict[dt.date, float]]]:
    """A sealed lake carrying ``symbol_count`` priced perps plus the benchmark.

    Each symbol's log-return scale is drawn from a fixed seed, so the ranking
    the momentum signal produces is stable run to run while the cross-section
    still moves date to date.
    """
    lake_root = workdir / "lake"
    (lake_root / "snapshots").mkdir(parents=True)
    staging = lake_root / "staging"
    staging.mkdir()

    generator = random.Random(WORLD_SEED)
    symbols = [f"SYM{index:02d}" for index in range(symbol_count)]
    symbols.append(BENCHMARK)

    closes: dict[str, dict[dt.date, float]] = {}
    for index, symbol in enumerate(symbols):
        sigma = 0.004 + 0.0008 * index
        price = 100.0
        series: dict[dt.date, float] = {}
        for day in PART_B_BAR_DAYS:
            shock = generator.gauss(0.0, sigma)
            price = max(1.0, price * (1.0 + shock))
            series[day] = round(price, 4)
        closes[symbol] = series

    for symbol, series in closes.items():
        for day in PART_B_BAR_DAYS:
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
                        "close": [f"{series[day]:.4f}"],
                        "volume": ["12.5"],
                    }
                ),
                partition / "part-0.parquet",
            )

    service = SnapshotService(lake_root)
    sealed = service.seal(sealed_at=dt.datetime(2026, 11, 1, tzinfo=dt.UTC))
    return service.mount(sealed.name), closes


class RecordingEndpoint:
    """A fake ``TargetEndpoint`` answering a dense, gapless real-branch series."""

    def __init__(self) -> None:
        self.requests: list[Any] = []

    def post(self, request: Any) -> TargetResponse:
        self.requests.append(request)
        first, last = request.date_range
        days: list[dt.date] = []
        day = first
        while day <= last:
            days.append(day)
            day = day + dt.timedelta(days=1)
        symbols = sorted(request.symbols)
        series = {
            day: {
                symbol: 0.001 * (index + 1) * (1.0 + 0.15 * (day - first).days)
                for index, symbol in enumerate(symbols)
            }
            for day in days
        }
        return TargetResponse(
            status=OK,
            node_id=request.node_id,
            target_series=series,
            charges_budget=True,
        )


@pytest.fixture(scope="module")
def sealed_world(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[Any, dict[str, dict[dt.date, float]]]:
    workdir = tmp_path_factory.mktemp("tail-decile-wiring-world")
    return _seal_world(workdir, symbol_count=PART_B_SYMBOL_COUNT)


@pytest.fixture(scope="module")
def thin_world(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[Any, dict[str, dict[dt.date, float]]]:
    """A world too small for any date's cross-section to hold two non-empty
    deciles — the refusal the feature owes such a date."""
    workdir = tmp_path_factory.mktemp("tail-decile-thin-world")
    return _seal_world(workdir, symbol_count=THIN_SYMBOL_COUNT)


def _build_context(
    tmp_path: Path,
    sealed: tuple[Any, dict[str, dict[dt.date, float]]],
    *,
    book: BookConfig,
    name: str,
) -> EvaluationContext:
    mount, closes = sealed
    config = load_cost_model()
    # Zero fees: the per-symbol charge cancels in a dollar-neutral book and
    # the turnover charge is zero, so the measured book_returns are exactly
    # the weighted forward returns the reconstruction below rebuilds.
    schedule = FeeSchedule(venue=config.venue, taker_bps=0.0, maker_bps=0.0)
    database_url = f"sqlite:///{tmp_path / name}.db"
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
        artifact_dir=tmp_path / f"artifacts-{name}",
        seed=WORLD_SEED,
        horizon=HORIZON,
        evaluation_dates=EVALUATION_DATES,
        sandbox_runtime="unisolated",
        book=book,
    )


def _capturing_evaluate(
    tmp_path: Path,
    sealed: tuple[Any, dict[str, dict[dt.date, float]]],
    *,
    book: BookConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Any, EvaluationContext, list[dict[str, Any]]]:
    """Evaluate one node under ``book``, recording every compute_node_metrics
    call's keyword arguments."""
    from evaluator import compute_node_metrics as real_compute_node_metrics

    calls: list[dict[str, Any]] = []

    def _capture(returns: Any, scores: Any, **kwargs: Any) -> Any:
        calls.append(
            {
                "returns": returns,
                "scores": scores,
                "betas": kwargs.get("betas"),
                "vols": kwargs.get("vols"),
                "weighting": kwargs.get("weighting"),
                "cost": kwargs.get("cost_per_unit_traded"),
            }
        )
        return real_compute_node_metrics(returns, scores, **kwargs)

    monkeypatch.setattr("orchestrator._evaluate.compute_node_metrics", _capture)

    context = _build_context(
        tmp_path,
        sealed,
        book=book,
        name=f"wiring-{uuid.uuid4().hex[:8]}",
    )
    node_id = str(uuid.uuid4())
    _plant_root(context.database_url, node_id=node_id, campaign_id=CAMPAIGN_ID)
    oracle = SubtreeOracle(RecordingEndpoint(), database_url=context.database_url)
    ledger = TrialLedger(context.database_url)
    answer = evaluate_node(
        node_id,
        CAMPAIGN_ID,
        0,
        WEIGHTING_SIGNAL_CODE,
        context=context,
        oracle=oracle,
        ledger=ledger,
    )
    return answer, context, calls


def test_tail_decile_books_equal_book_weights_over_the_chain(
    sealed_world: tuple[Any, dict[str, dict[dt.date, float]]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answer, _, calls = _capturing_evaluate(
        tmp_path,
        sealed_world,
        book=BookConfig(beta_neutral=False, weighting=TAIL_DECILE_WEIGHTING),
        monkeypatch=monkeypatch,
    )

    assert answer.fail_class is None, answer.fail_detail
    assert len(calls) == 2  # the net figure, then the gross diagnostic
    net_call, gross_call = calls
    # The weighting rides the call in both chains — the gross diagnostic is
    # measured over the same book as the net figure, never a different one.
    assert net_call["weighting"] == TAIL_DECILE_WEIGHTING
    assert gross_call["weighting"] == TAIL_DECILE_WEIGHTING
    # No vols panel: the tail-decile book is a function of the scores alone.
    assert net_call["vols"] is None
    assert gross_call["vols"] is None
    assert net_call["cost"] == 0.0  # the zero-fee schedule, as built

    scores = net_call["scores"]
    metrics = answer.metrics
    assert metrics is not None
    series = net_call["returns"].series[metrics.horizon]
    checked = 0
    for day in series.dates():
        score_row = scores.get(day)
        if not score_row:
            continue
        returns_row = series.at(day)
        book_symbols = sorted(set(score_row) & set(returns_row))
        weights = book_weights(
            {symbol: score_row[symbol] for symbol in book_symbols},
            None,
            weighting=TAIL_DECILE_WEIGHTING,
        )
        # Gross stays 1 and net 0, with the middle deciles empty: the whole
        # point of the weighting, verified on every measured date.
        assert math.fsum(abs(w) for w in weights.values()) == pytest.approx(
            1.0, rel=1e-12
        )
        assert math.fsum(weights.values()) == pytest.approx(0.0, abs=1e-12)
        non_zero = [w for w in weights.values() if w != 0.0]
        assert non_zero, day
        assert len(non_zero) == 2 * (len(book_symbols) // 10)
        expected = math.fsum(
            weights[symbol] * returns_row[symbol] for symbol in book_symbols
        )
        assert metrics.book_returns[day] == pytest.approx(
            expected, rel=1e-12, abs=1e-15
        )
        checked += 1
    assert checked >= 20  # the whole grid was measured, not a lucky date


def test_tail_decile_records_the_names_each_leg_held(
    sealed_world: tuple[Any, dict[str, dict[dt.date, float]]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``tail_k`` — the record's own statement of how many names each leg
    held, ``floor(n/10)`` for that date's joined cross-section."""
    answer, _, calls = _capturing_evaluate(
        tmp_path,
        sealed_world,
        book=BookConfig(beta_neutral=False, weighting=TAIL_DECILE_WEIGHTING),
        monkeypatch=monkeypatch,
    )
    assert answer.fail_class is None, answer.fail_detail
    metrics = answer.metrics
    assert metrics is not None
    scores = calls[0]["scores"]
    series = calls[0]["returns"].series[metrics.horizon]
    assert set(metrics.tail_k) == set(metrics.book_returns)
    for day, count in metrics.tail_k.items():
        joined = set(scores[day]) & set(series.at(day))
        assert count == len(joined) // 10


def test_tail_decile_book_differs_from_the_z_book(
    sealed_world: tuple[Any, dict[str, dict[dt.date, float]]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The wiring is not vacuous: over the same scores the tail-decile book
    really is a different portfolio from the z-weighted one — the middle
    deciles that the z book weights are held flat here."""
    answer, _, calls = _capturing_evaluate(
        tmp_path,
        sealed_world,
        book=BookConfig(beta_neutral=False, weighting=TAIL_DECILE_WEIGHTING),
        monkeypatch=monkeypatch,
    )
    assert answer.fail_class is None, answer.fail_detail
    scores = calls[0]["scores"]
    day = next(day for day in sorted(scores) if scores[day])
    score_row = scores[day]
    tail = book_weights(score_row, None, weighting=TAIL_DECILE_WEIGHTING)
    plain = book_weights(score_row, None)
    assert any(
        tail[symbol] != pytest.approx(plain[symbol], rel=1e-9)
        for symbol in score_row
    )
    # And the difference is the design: every name outside the two tails
    # carries exactly nothing.
    assert sum(1 for value in tail.values() if value == 0.0) == len(score_row) - 4


def test_tail_decile_composes_with_beta_neutral(
    sealed_world: tuple[Any, dict[str, dict[dt.date, float]]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answer, _, calls = _capturing_evaluate(
        tmp_path,
        sealed_world,
        book=BookConfig(
            beta_neutral=True,
            beta_window_days=20,
            beta_benchmark=BENCHMARK,
            weighting=TAIL_DECILE_WEIGHTING,
        ),
        monkeypatch=monkeypatch,
    )

    assert answer.fail_class is None, answer.fail_detail
    net_call = calls[0]
    scores, betas = net_call["scores"], net_call["betas"]
    assert betas is not None
    assert net_call["vols"] is None
    assert net_call["weighting"] == TAIL_DECILE_WEIGHTING

    metrics = answer.metrics
    assert metrics is not None
    series = net_call["returns"].series[metrics.horizon]
    checked = 0
    for day in series.dates():
        score_row = scores.get(day)
        if not score_row:
            continue
        returns_row = series.at(day)
        book_symbols = sorted(set(score_row) & set(returns_row))
        # book_weights, called the way today's callers call it — betas
        # positional — with the new input keyword-only.
        weights = book_weights(
            {symbol: score_row[symbol] for symbol in book_symbols},
            betas[day],
            weighting=TAIL_DECILE_WEIGHTING,
        )
        assert math.fsum(abs(w) for w in weights.values()) == pytest.approx(
            1.0, rel=1e-12
        )
        expected = math.fsum(
            weights[symbol] * returns_row[symbol] for symbol in book_symbols
        )
        assert metrics.book_returns[day] == pytest.approx(
            expected, rel=1e-12, abs=1e-15
        )
        checked += 1
    assert checked >= 20


def test_too_thin_a_cross_section_is_refused_naming_the_date_and_count(
    thin_world: tuple[Any, dict[str, dict[dt.date, float]]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Twelve priced names (plus the benchmark) hold ``floor(13/10) = 1`` per
    leg, which is not a decile but a directional bet — so the node is refused,
    and the recorded detail names the date the thin cross-section belongs to
    and how many names it held.

    The refusal is a node failure, not a raised exception: the pipeline turns
    every chain error into ``fail_class``/``fail_detail`` on the answered
    evaluation (the same path the executor's own failures take), which is
    where the campaign's operator reads it.
    """
    answer, _, _ = _capturing_evaluate(
        tmp_path,
        thin_world,
        book=BookConfig(beta_neutral=False, weighting=TAIL_DECILE_WEIGHTING),
        monkeypatch=monkeypatch,
    )
    assert answer.fail_class == EvaluatorMetricsError.__name__
    assert answer.metrics is None
    detail = answer.fail_detail or ""
    assert EVALUATION_DATES[0].isoformat() in detail
    # The priced universe, benchmark included — every name the date scored.
    assert f"{THIN_SYMBOL_COUNT + 1} scored symbols" in detail
    assert "floor(13/10) = 1" in detail
