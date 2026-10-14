"""additions_spec_forward_shadow.xml, "Forward Shadow" feature 2.

System computes a research node's current target weights from the latest
sealed data, so that a stored signal can be traded forward on the venue it
was scored for: :func:`orchestrator._shadow.shadow_weights` reproduces
:func:`orchestrator._evaluate.evaluate_node`'s own chain for one date and
answers a :class:`~orchestrator._shadow.ShadowWeights`.

Over one tmp sealed snapshot carrying ``bars``, ``futbars`` and ``funding``
for four scored symbols (AAA, BBB, CCC, DDD, each with a positive,
distinct beta against the benchmark) and the beta benchmark itself
(BTCUSDT), loaded through the real :func:`~orchestrator._context.load_evaluation_context`
and run under the hardened-subprocess sandbox :mod:`test_evaluate`'s own
suite uses (``sandbox_runtime: "unisolated"``), this suite covers:

* the shadow's weights equal ``evaluator.book_weights`` applied to the
  same z-scores and betas the reproduced chain itself computes for the
  date, directly, with the shared helpers ``evaluate_node`` calls;
* net weight 0, gross 1 and book beta ~0 when the book is beta-neutral;
* ``allowed_symbols`` is applied *before* z-scoring — the kept symbols'
  weights are the ones a z-score over the restricted cross-section alone
  would give, not the full cross-section's weights with a symbol dropped
  after the fact;
* no ledger, node or trial-ledger row is ever written;
* a planted future bars/futbars row — present in one sealed snapshot,
  absent from a second, otherwise identical, snapshot truncated at
  ``as_of`` — never changes the answer;
* the three named refusals: a non-conforming score vector, fewer than two
  scored symbols in a leg, and a beta-neutral book whose benchmark carries
  no close at all.

No test opens a network connection, reads a real credential, or writes
outside a pytest temporary directory. Runs under pytest-xdist: every
fixture builds its own temporary database and lake, with no shared
module-level mutable state across tests.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import json
import sqlite3
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from types import ModuleType
from typing import Any
from urllib.parse import unquote, urlparse

import cost_model
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from evaluator import SignalExecution, book_weights, execute_signal, resolve_window
from orchestrator._context import (
    EvaluationContext,
    compute_betas,
    load_evaluation_context,
    signal_sandbox,
)
from orchestrator._evaluate import (
    _END_OF_DAY,
    _drop_unpriced_symbols,
    _materialize_from_context,
    _score_rebalance_dates,
)
from orchestrator._shadow import ShadowError, ShadowWeights, shadow_weights
from snapshot import SnapshotService

REPO_ROOT = Path(__file__).resolve().parents[3]
VERSIONS_DIR = REPO_ROOT / "migrations" / "versions"
NODE_TABLE_MIGRATIONS = ("0118_node_table", "0114_node_metrics")
TRIAL_LEDGER_MIGRATION = "0112_trial_ledger"

USDM_PATH = Path(cost_model.__file__).with_name("binance_usdm.yaml")

_TS = pa.timestamp("us", tz="UTC")

#: Six scored symbols, each a fixed positive multiple ("beta") of the
#: benchmark's own daily returns — exact, noise-free, so the OLS slope
#: :func:`orchestrator._context.compute_betas` recovers is the configured
#: beta to floating-point precision, and every leg a z-score split could
#: ever produce carries a strictly positive average beta (the
#: beta-neutral rescale's own precondition, see ``_beta_neutral_weights``).
#: An *even* count throughout, deliberately: z-scoring ``n`` symbols with
#: no ties splits them evenly around the mean rank only when ``n`` is
#: even — an odd cross-section always leaves exactly one symbol sitting
#: on the mean rank itself (z exactly 0, in neither leg), which would
#: make every "happy path" test flirt with the module's own "fewer than
#: two symbols in a leg" refusal for a reason that has nothing to do with
#: what the test means to exercise.
SYMBOLS = ("AAA", "BBB", "CCC", "DDD", "EEE", "FFF")
SYMBOL_BETA = {
    "AAA": 0.4,
    "BBB": 0.6,
    "CCC": 0.9,
    "DDD": 1.2,
    "EEE": 1.5,
    "FFF": 1.9,
}
BENCHMARK = "BTCUSDT"

FIRST_DAY = dt.date(2026, 1, 1)
DAYS = tuple(FIRST_DAY + dt.timedelta(days=offset) for offset in range(16))
LAST_DAY = DAYS[-1]
EARLY_DAY = DAYS[10]
LOOKBACK = 5
BETA_WINDOW_DAYS = 5

#: One daily return per day after the first — varied (never constant), so
#: the benchmark's own window carries real variance for the OLS slope's
#: denominator, and distinct enough across days that a symbol's trailing
#: momentum differs from one rebalance date to the next.
BENCH_RETURNS = (
    0.02, -0.01, 0.015, -0.02, 0.01, 0.03, -0.015, 0.025,
    -0.01, 0.02, -0.03, 0.015, 0.01, -0.02, 0.025,
)
assert len(BENCH_RETURNS) == len(DAYS) - 1


def _price_path(beta: float) -> dict[dt.date, float]:
    prices = {DAYS[0]: 100.0}
    for offset, r in enumerate(BENCH_RETURNS):
        prices[DAYS[offset + 1]] = prices[DAYS[offset]] * (1.0 + beta * r)
    return prices


BENCH_PRICES = _price_path(1.0)
SYMBOL_PRICES = {symbol: _price_path(beta) for symbol, beta in SYMBOL_BETA.items()}

#: A hand-written momentum signal, the same trailing-window shape
#: ``test_evaluate.py``'s own ``MOMENTUM_SIGNAL_CODE`` takes — it reads
#: only the "bars" stream (``ctx.bars("1d")``), which is point-in-time
#: sliced to the decision date regardless of ``instrument``.
MOMENTUM_SIGNAL_CODE = f"""
import polars as pl

def signal(ctx, seed):
    bars = ctx.bars("1d")
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

#: A signal with no disallowed import that raises at run time — the
#: sandbox's own "crash" resource failure, recorded as a non-conforming
#: vector rather than escaping ``execute_signal``.
CRASHING_SIGNAL_CODE = """
def signal(ctx, seed):
    raise ValueError("this signal always crashes")
"""


# -- Migrations and raw-SQL reads ------------------------------------------------


def _load_migration(revision: str) -> ModuleType:
    path = VERSIONS_DIR / f"{revision}.py"
    if not path.is_file():
        raise AssertionError(f"{revision} is not at {path}")
    spec = importlib.util.spec_from_file_location(
        f"_orchestrator_test_shadow_{revision}", path
    )
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _path_of(database_url: str) -> Path:
    parsed = urlparse(database_url)
    return Path(unquote(parsed.path).removeprefix("/"))


# -- The sealed world: bars, futbars and funding for every symbol ---------------


def _stamp(day: dt.date) -> Any:
    return dt.datetime.combine(day, dt.time(0), tzinfo=dt.UTC)


def _write_bars(staging: Path, symbol: str, day: dt.date, close: float) -> None:
    partition = staging / "bars" / f"symbol={symbol}" / f"date={day.isoformat()}"
    partition.mkdir(parents=True)
    pq.write_table(
        pa.table(
            {
                "symbol": [symbol],
                "open_time": pa.array([_stamp(day)], type=_TS),
                "close": [str(close)],
                "volume": ["10.0"],
            }
        ),
        partition / "part-0.parquet",
    )


def _write_futbars(staging: Path, symbol: str, day: dt.date, fut_close: float) -> None:
    partition = staging / "futbars" / f"symbol={symbol}" / f"date={day.isoformat()}"
    partition.mkdir(parents=True)
    pq.write_table(
        pa.table(
            {
                "symbol": [symbol],
                "date": pa.array([_stamp(day)], type=_TS),
                "fut_close": [str(fut_close)],
                "fut_volume": ["1000.0"],
                "taker_buy_volume": ["400.0"],
                "quote_volume": ["100000.0"],
            }
        ),
        partition / "part-0.parquet",
    )


def _write_funding(staging: Path, symbol: str, day: dt.date) -> None:
    partition = staging / "funding" / f"symbol={symbol}" / f"date={day.isoformat()}"
    partition.mkdir(parents=True)
    pq.write_table(
        pa.table(
            {
                "symbol": [symbol],
                "date": pa.array([_stamp(day)], type=_TS),
                "funding_rate_sum": ["0.0001"],
                "funding_rate_last": ["0.0001"],
                "n_settlements": pa.array([3], type=pa.int64()),
            }
        ),
        partition / "part-0.parquet",
    )


def _seal_world(lake_root: Path, *, days: tuple[dt.date, ...]) -> Any:
    """Stage and seal the world.

    The scored symbols get ``bars`` (the signal's own window, and the
    point-in-time universe ``pit_universe`` derives *only* from the bars
    stream), ``futbars`` (``context.closes`` under the perp instrument) and
    ``funding``. The benchmark gets ``futbars`` (and ``funding``) only —
    deliberately no ``bars`` at all, so it never joins the bars-derived
    roster and is never itself scored or traded; it exists purely as a
    beta regressor through ``context.closes``, the same split a real
    deployment's beta benchmark (not one of the signal's own tradable
    names) would carry.
    """
    (lake_root / "snapshots").mkdir(parents=True)
    staging = lake_root / "staging"
    for symbol in SYMBOLS:
        prices = SYMBOL_PRICES[symbol]
        for day in days:
            _write_bars(staging, symbol, day, prices[day])
            _write_futbars(staging, symbol, day, prices[day])
            _write_funding(staging, symbol, day)
    for day in days:
        _write_futbars(staging, BENCHMARK, day, BENCH_PRICES[day])
        _write_funding(staging, BENCHMARK, day)
    service = SnapshotService(lake_root)
    sealed = service.seal(sealed_at=dt.datetime(2026, 11, 1, tzinfo=dt.UTC))
    return service, sealed


@pytest.fixture(scope="module")
def sealed_world(tmp_path_factory: pytest.TempPathFactory) -> Any:
    """The full world: every one of :data:`DAYS`, through :data:`LAST_DAY`."""
    workdir = tmp_path_factory.mktemp("shadow-weights-world")
    return _seal_world(workdir / "lake", days=DAYS)


@pytest.fixture(scope="module")
def truncated_world(tmp_path_factory: pytest.TempPathFactory) -> Any:
    """The same world, sealed with nothing after :data:`EARLY_DAY` at all —
    the "planted future row" test's control: a snapshot that *cannot* have
    read a row after ``EARLY_DAY`` because no such row was ever staged.
    """
    workdir = tmp_path_factory.mktemp("shadow-weights-truncated-world")
    cutoff = DAYS.index(EARLY_DAY) + 1
    return _seal_world(workdir / "lake", days=DAYS[:cutoff])


# -- Loading a context over a sealed world ---------------------------------------


def _bwrap_dir(tmp_path: Path) -> Path:
    """A stub ``bwrap`` on ``PATH`` — satisfies only the loader's own gate
    check (:mod:`orchestrator._context`'s ``_sandbox_runtime``); the real
    sandbox execution later shells out to the host's genuine ``bwrap``
    through its own, unmodified process environment, exactly as
    ``test_perp_instrument.py`` and ``test_book_beta_neutral.py`` already
    rely on.
    """
    bwrap_dir = tmp_path / "bin"
    bwrap_dir.mkdir(exist_ok=True)
    bwrap = bwrap_dir / "bwrap"
    if not bwrap.exists():
        bwrap.write_text("#! /bin/sh\n", encoding="utf-8")
        bwrap.chmod(0o755)
    return bwrap_dir


def _context(
    sealed_path: Path,
    tmp_path: Path,
    *,
    name: str,
    evaluation_date: dt.date = LAST_DAY,
    book: dict[str, Any] | None = None,
) -> EvaluationContext:
    document: dict[str, Any] = {
        "snapshot_mount": str(sealed_path),
        "evaluation_dates": [evaluation_date.isoformat()],
        "horizon": 1,
        "seed": 20261014,
        "epoch_id": "epoch-shadow-weights-test",
        "artifact_dir": str(tmp_path / f"artifacts-{name}"),
        "sandbox_runtime": "unisolated",
        "acknowledge_unisolated": True,
        "instrument": "perp",
    }
    if book is not None:
        document["book"] = book
    config_path = tmp_path / f"evaluation-{name}.json"
    config_path.write_text(json.dumps(document), encoding="utf-8")
    environment = {
        "NULLIUS_EVALUATION_CONFIG": str(config_path),
        "DATABASE_URL": f"sqlite:///{tmp_path / f'{name}.db'}",
        "NULLIUS_EVALUATOR_IMAGE": "ghcr.io/nullius/evaluator@sha256:" + "ab" * 32,
        "NULLIUS_COST_MODEL_PATH": str(USDM_PATH),
        "PATH": str(_bwrap_dir(tmp_path)),
    }
    context = load_evaluation_context(environment)
    assert context is not None
    return context


BETA_NEUTRAL_BOOK: dict[str, Any] = {
    "beta_neutral": True,
    "beta_window_days": BETA_WINDOW_DAYS,
    "beta_benchmark": BENCHMARK,
}


# -- The reference chain: the same helpers evaluate_node's own chain calls ------


def _reference_scores_and_betas(
    context: EvaluationContext, code: str, as_of: dt.date, *, beta_neutral: bool
) -> tuple[dict[str, float], dict[str, float] | None]:
    executor = signal_sandbox(context)
    decision_time = dt.datetime.combine(as_of, _END_OF_DAY)
    resolution = resolve_window(context.snapshot, decision_time)
    execution = execute_signal(
        resolution,
        code,
        seed=context.seed,
        rebalance_dates=[as_of],
        sandbox=executor,
        materialize=_materialize_from_context(context),
    )
    execution, _dropped = _drop_unpriced_symbols(execution, context)
    scores, _flat = _score_rebalance_dates(execution, "reference")
    day_scores = scores[as_of]
    betas = None
    if beta_neutral:
        betas = dict(compute_betas(context, {as_of: day_scores})[as_of])
    return day_scores, betas


# -- The shadow's weights equal book_weights of the evaluation's own figures ----


def test_weights_equal_book_weights_of_the_evaluations_own_scores_and_betas(
    sealed_world: Any, tmp_path: Path
) -> None:
    _service, sealed = sealed_world
    context = _context(
        sealed.path, tmp_path, name="reference", book=BETA_NEUTRAL_BOOK
    )

    result = shadow_weights(context, MOMENTUM_SIGNAL_CODE, as_of=LAST_DAY)

    day_scores, betas = _reference_scores_and_betas(
        context, MOMENTUM_SIGNAL_CODE, LAST_DAY, beta_neutral=True
    )
    expected = book_weights(day_scores, betas)

    assert isinstance(result, ShadowWeights)
    assert result.as_of == LAST_DAY
    assert result.weights == pytest.approx(expected, abs=1e-12)
    assert result.code_hash == hashlib.sha256(
        MOMENTUM_SIGNAL_CODE.encode("utf-8")
    ).hexdigest()
    assert result.n_scored == len(expected)
    assert result.n_dropped_unpriced == 0
    assert result.n_dropped_unmapped == 0


def test_plain_book_is_net_zero_and_gross_one(
    sealed_world: Any, tmp_path: Path
) -> None:
    _service, sealed = sealed_world
    context = _context(sealed.path, tmp_path, name="plain-book")

    result = shadow_weights(context, MOMENTUM_SIGNAL_CODE, as_of=LAST_DAY)

    assert result.weights
    assert sum(result.weights.values()) == pytest.approx(0.0, abs=1e-9)
    assert sum(abs(w) for w in result.weights.values()) == pytest.approx(1.0, abs=1e-9)
    assert result.book_beta is None


def test_beta_neutral_book_is_beta_neutral_and_gross_one(
    sealed_world: Any, tmp_path: Path
) -> None:
    """``evaluator.book_weights``' own suite already pins that the
    beta-neutral rescale keeps gross exposure at 1 and the book's net
    *beta* at 0 — it does **not** claim the book stays net dollar-*weight*
    zero too (``test_beta_neutral_book_stays_gross_one`` in
    ``test_book_weights.py`` tests gross and beta separately from the
    plain book's own net-zero claim, precisely because unequal long- and
    short-leg betas push the two legs' gross apart by construction, see
    ``_beta_neutral_weights``'s own ``gl`` derivation). So this test checks
    exactly what that contract promises for a beta-neutral book — gross 1,
    book beta ~0 — and :func:`test_plain_book_is_net_zero_and_gross_one`
    above is where this module's own "net weight 0" claim lives, over the
    plain book the spec's convention actually makes it for.
    """
    _service, sealed = sealed_world
    context = _context(
        sealed.path, tmp_path, name="beta-neutral", book=BETA_NEUTRAL_BOOK
    )

    result = shadow_weights(context, MOMENTUM_SIGNAL_CODE, as_of=LAST_DAY)

    assert result.weights
    assert sum(abs(w) for w in result.weights.values()) == pytest.approx(1.0, abs=1e-9)
    assert result.book_beta is not None
    assert result.book_beta == pytest.approx(0.0, abs=1e-6)


# -- allowed_symbols: applied before z-scoring -----------------------------------


def test_allowed_symbols_is_applied_before_zscoring(
    sealed_world: Any, tmp_path: Path
) -> None:
    _service, sealed = sealed_world
    context = _context(sealed.path, tmp_path, name="allowed-symbols")
    # Even-sized, as every happy-path set in this suite is (see SYMBOLS'
    # own comment): a clean 2-long/2-short split with no symbol stranded
    # on the mean rank.
    allowed = {"AAA", "BBB", "CCC", "DDD"}

    result = shadow_weights(
        context, MOMENTUM_SIGNAL_CODE, as_of=LAST_DAY, allowed_symbols=allowed
    )

    assert set(result.weights) == allowed
    assert result.n_dropped_unmapped == 2
    assert result.n_scored == 4

    import polars as pl

    executor = signal_sandbox(context)
    decision_time = dt.datetime.combine(LAST_DAY, _END_OF_DAY)
    resolution = resolve_window(context.snapshot, decision_time)
    execution = execute_signal(
        resolution,
        MOMENTUM_SIGNAL_CODE,
        seed=context.seed,
        rebalance_dates=[LAST_DAY],
        sandbox=executor,
        materialize=_materialize_from_context(context),
    )
    execution, _dropped = _drop_unpriced_symbols(execution, context)
    vector = execution.vector(LAST_DAY)
    assert vector is not None
    keep_mask = [symbol in allowed for symbol in vector.universe]
    kept_universe = tuple(
        symbol for symbol, keep in zip(vector.universe, keep_mask) if keep
    )
    kept_scores = vector.scores.filter(pl.Series(keep_mask, dtype=pl.Boolean))
    restricted = SignalExecution(
        snapshot_name=execution.snapshot_name,
        code_hash=execution.code_hash,
        seed=execution.seed,
        vectors={LAST_DAY: replace(vector, universe=kept_universe, scores=kept_scores)},
    )
    scores, _flat = _score_rebalance_dates(restricted, "reference-allowed")
    expected = book_weights(scores[LAST_DAY])

    assert result.weights == pytest.approx(expected, abs=1e-12)


# -- No ledger, node or trial row is ever written --------------------------------


def test_writes_no_ledger_node_or_trial_row(sealed_world: Any, tmp_path: Path) -> None:
    _service, sealed = sealed_world
    context = _context(sealed.path, tmp_path, name="no-writes")
    for revision in (*NODE_TABLE_MIGRATIONS, TRIAL_LEDGER_MIGRATION):
        _load_migration(revision).apply(context.database_url)

    shadow_weights(context, MOMENTUM_SIGNAL_CODE, as_of=LAST_DAY)

    with closing(sqlite3.connect(_path_of(context.database_url))) as connection:
        node_count = connection.execute("SELECT COUNT(*) FROM node").fetchone()[0]
        trial_count = connection.execute(
            "SELECT COUNT(*) FROM trial_ledger"
        ).fetchone()[0]
    assert node_count == 0
    assert trial_count == 0


# -- Point-in-time: a planted future row never changes the answer ---------------


def test_a_planted_future_row_does_not_change_the_answer(
    sealed_world: Any, truncated_world: Any, tmp_path: Path
) -> None:
    _full_service, full_sealed = sealed_world
    _truncated_service, truncated_sealed = truncated_world

    full_context = _context(
        full_sealed.path,
        tmp_path,
        name="future-full",
        evaluation_date=EARLY_DAY,
        book=BETA_NEUTRAL_BOOK,
    )
    truncated_context = _context(
        truncated_sealed.path,
        tmp_path,
        name="future-truncated",
        evaluation_date=EARLY_DAY,
        book=BETA_NEUTRAL_BOOK,
    )

    with_future = shadow_weights(full_context, MOMENTUM_SIGNAL_CODE, as_of=EARLY_DAY)
    without_future = shadow_weights(
        truncated_context, MOMENTUM_SIGNAL_CODE, as_of=EARLY_DAY
    )

    assert with_future.weights == pytest.approx(without_future.weights, abs=1e-12)
    assert with_future.book_beta == pytest.approx(without_future.book_beta, abs=1e-9)
    assert with_future.n_scored == without_future.n_scored
    assert with_future.code_hash == without_future.code_hash


# -- The refusals -----------------------------------------------------------------


def test_refuses_a_non_conforming_score_vector(sealed_world: Any, tmp_path: Path) -> None:
    _service, sealed = sealed_world
    context = _context(sealed.path, tmp_path, name="crashing-signal")

    with pytest.raises(ShadowError):
        shadow_weights(context, CRASHING_SIGNAL_CODE, as_of=LAST_DAY)


def test_refuses_fewer_than_two_symbols_in_a_leg(
    sealed_world: Any, tmp_path: Path
) -> None:
    _service, sealed = sealed_world
    context = _context(sealed.path, tmp_path, name="thin-legs")

    with pytest.raises(ShadowError, match="leg"):
        shadow_weights(
            context,
            MOMENTUM_SIGNAL_CODE,
            as_of=LAST_DAY,
            allowed_symbols={"AAA", "BBB"},
        )


def test_refuses_an_as_of_with_no_benchmark_close_when_beta_neutral(
    sealed_world: Any, tmp_path: Path
) -> None:
    _service, sealed = sealed_world
    book = {
        "beta_neutral": True,
        "beta_window_days": BETA_WINDOW_DAYS,
        "beta_benchmark": "ZZZUSDT",
    }
    context = _context(sealed.path, tmp_path, name="no-benchmark-close", book=book)

    with pytest.raises(ShadowError, match="benchmark"):
        shadow_weights(context, MOMENTUM_SIGNAL_CODE, as_of=LAST_DAY)
